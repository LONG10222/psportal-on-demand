// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	"sort"
	"time"
)

type fastestSelection struct {
	current, challenger string
	rounds              int
	switchedAt          time.Time
}

// choose requires two measured rounds and a 30-second hold-down for a healthy
// incumbent. Failed incumbents bypass the hold-down to preserve connectivity.
func (f *fastestSelection) choose(nodes []*node, threshold int, now time.Time, measured bool) string {
	var best, current *node
	for _, n := range nodes {
		if !n.healthy || n.delayMS < 0 {
			continue
		}
		if n.proxy.Name() == f.current {
			current = n
		}
		if best == nil || n.delayMS < best.delayMS || (n.delayMS == best.delayMS && n.proxy.Name() < best.proxy.Name()) {
			best = n
		}
	}
	if best == nil {
		f.current = ""
		f.challenger, f.rounds = "", 0
		return ""
	}
	if current == nil {
		f.current, f.switchedAt = best.proxy.Name(), now
		f.challenger, f.rounds = "", 0
	} else if measured {
		name := best.proxy.Name()
		if name != f.current && current.delayMS-best.delayMS > int64(threshold) {
			if f.challenger == name {
				f.rounds++
			} else {
				f.challenger, f.rounds = name, 1
			}
			if f.rounds >= 2 && now.Sub(f.switchedAt) >= 30*time.Second {
				f.current, f.switchedAt = name, now
				f.challenger, f.rounds = "", 0
			}
		} else {
			f.challenger, f.rounds = "", 0
		}
	}
	return f.current
}

func nodeDelay(n *node) any {
	if !n.healthy || n.delayMS < 0 {
		return nil
	}
	return n.delayMS
}

// Caller holds c.mu. Copies protect policy order from concurrent live changes.
func (c *embeddedCore) candidatesLocked() []*node {
	nodes := make([]*node, 0, len(c.nodes))
	for _, n := range c.nodes {
		if n.healthy && (c.mode != "fixed" || n.proxy.Name() == c.preferred) {
			nodes = append(nodes, n)
		}
	}
	cfg := c.cfg
	cfg.SelectionMode, cfg.PreferredNode = c.mode, c.preferred
	orderNodes(nodes, cfg)
	if c.mode == "fastest" {
		sort.SliceStable(nodes, func(i, j int) bool {
			if nodes[i].proxy.Name() == c.selected {
				return nodes[j].proxy.Name() != c.selected
			}
			if nodes[j].proxy.Name() == c.selected {
				return false
			}
			return nodes[i].delayMS < nodes[j].delayMS
		})
	}
	return nodes
}
func (c *embeddedCore) chooseLocked(measured bool) {
	if c.mode == "fastest" {
		if c.legacyFastest {
			// The existing iOS command picks the current measured minimum;
			// threshold-aware callers retain the stable policy below.
			c.fastest = fastestSelection{}
		}
		c.selected = c.fastest.choose(c.nodes, c.thresholdMS, time.Now(), measured)
	} else if c.mode == "fixed" {
		c.selected = c.preferred
	} else {
		nodes := c.candidatesLocked()
		c.selected = ""
		if len(nodes) > 0 {
			c.selected = nodes[0].proxy.Name()
		}
	}
}

// Caller holds c.mu. A missing fixed node must remain fail-closed while the
// rest of the parsed pool stays available for an explicit user selection.
func (c *embeddedCore) selectionErrorLocked() error {
	if c.mode == "fixed" {
		found := false
		for _, n := range c.nodes {
			if n.proxy.Name() == c.preferred {
				found = true
				break
			}
		}
		if !found {
			return errFixedMissing
		}
	}
	if len(c.candidatesLocked()) == 0 {
		return errNoHealthy
	}
	return nil
}

// Caller holds c.mu. Health status describes the selected policy, including a
// failed fixed node even when an unrelated fallback node is healthy.
func (c *embeddedCore) updateHealthLocked(measured bool) {
	if c.closed || c.ctx.Err() != nil {
		return
	}
	c.chooseLocked(measured)
	if err := c.selectionErrorLocked(); err != nil {
		c.state, c.lastError = "error", err.Error()
	} else {
		c.state, c.lastError = "running", ""
	}
}

func (c *embeddedCore) prepare() error {
	c.operationMu.Lock()
	defer c.operationMu.Unlock()
	c.mu.Lock()
	if c.closed || c.ctx.Err() != nil {
		c.mu.Unlock()
		return errStopped
	}
	c.preparing = true
	c.wg.Add(1)
	c.mu.Unlock()
	defer c.wg.Done()
	defer func() { c.mu.Lock(); c.preparing = false; c.mu.Unlock() }()
	ctx, cancel := context.WithTimeout(c.ctx, time.Duration(c.cfg.WakeupTimeout)*time.Second)
	defer cancel()
	fresh, err := c.acquire(ctx)
	if err != nil {
		return err
	}
	defer c.Release()
	if fresh {
		return nil
	}
	c.mu.Lock()
	nodes := append([]*node(nil), c.nodes...)
	c.mu.Unlock()
	c.checkHealth(ctx, nodes)
	if ctx.Err() != nil {
		return ctx.Err()
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed || c.ctx.Err() != nil {
		return errStopped
	}
	if err := c.selectionErrorLocked(); err != nil {
		return err
	}
	c.lastError = ""
	return nil
}

func (c *embeddedCore) selectNode(mode, name string, threshold *int) error {
	return c.changeSelection(mode, name, threshold, true)
}

// changeSelection stages measurements before committing a requested policy.
// Tests may disable measurement to exercise the policy state machine directly.
func (c *embeddedCore) changeSelection(mode, name string, threshold *int, measure bool) error {
	if mode != "auto" && mode != "prefer" && mode != "fixed" && mode != "fastest" {
		return errors.New("unsupported selection mode")
	}
	if (mode == "fixed" || mode == "prefer") && !validNodeName(name) {
		return errors.New("invalid preferred node")
	}
	if threshold != nil && (*threshold < 0 || *threshold > 60000) {
		return errors.New("invalid switching threshold")
	}
	c.operationMu.Lock()
	defer c.operationMu.Unlock()
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.closed || c.ctx.Err() != nil {
		return errStopped
	}
	// Only select names from the loaded pool; never manufacture an adapter.
	if len(c.nodes) == 0 {
		return errors.New("load live nodes before selecting")
	}
	if mode == "fixed" || mode == "prefer" {
		found := false
		for _, n := range c.nodes {
			if n.proxy.Name() == name {
				found = true
			}
		}
		if !found {
			return errors.New("selected node is missing from the subscription")
		}
	} else {
		name = ""
	}
	if measure && mode != "auto" {
		probes := make([]*node, 0, len(c.nodes))
		for _, n := range c.nodes {
			if mode == "fastest" || n.proxy.Name() == name {
				probes = append(probes, n)
			}
		}
		c.preparing = true
		c.active++
		c.wg.Add(1)
		c.mu.Unlock()
		ctx, cancel := context.WithTimeout(c.ctx, time.Duration(c.cfg.WakeupTimeout)*time.Second)
		c.measureNodes(ctx, probes, false)
		probeError := ctx.Err()
		cancel()
		c.mu.Lock()
		c.preparing = false
		c.active--
		c.lastUsed = time.Now()
		c.wg.Done()
		if c.closed || c.ctx.Err() != nil {
			return errStopped
		}
		c.updateHealthLocked(false)
		if probeError != nil {
			return probeError
		}
		if !hasHealthy(probes) {
			return errNoHealthy
		}
	}
	if c.mode != mode || c.legacyFastest {
		c.fastest = fastestSelection{}
	}
	c.legacyFastest = false
	c.mode, c.preferred = mode, name
	if threshold != nil {
		if c.thresholdMS != *threshold {
			c.fastest.challenger, c.fastest.rounds = "", 0
		}
		c.thresholdMS = *threshold
	}
	c.updateHealthLocked(measure && mode == "fastest")
	c.lastUsed = time.Now()
	return nil
}
