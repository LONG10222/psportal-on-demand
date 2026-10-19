// SPDX-License-Identifier: GPL-3.0-only
package androidcore

import (
	"encoding/json"
	"errors"
	"time"

	"github.com/metacubex/mihomo/adapter/outboundgroup"
)

// Choices are returned on demand, not multiplied into every status snapshot.
// The sanitized profile bounds each group and contains only explicit members.
func groupChoices(group map[string]any) []string {
	choices := []string{}
	seen := map[string]bool{}
	refs, _ := group["proxies"].([]any)
	for _, ref := range refs {
		name, ok := ref.(string)
		if ok && !seen[name] {
			choices = append(choices, name)
			seen[name] = true
		}
	}
	return choices
}
func containsGroupChoice(group map[string]any, choice string) bool {
	for _, member := range groupChoices(group) {
		if member == choice {
			return true
		}
	}
	return false
}
func (e *Engine) selectableGroupLocked(name string) (map[string]any, *outboundgroup.Selector, error) {
	if e.closed || e.ctx.Err() != nil || e.current == nil || e.profile.generated || !safeName(name) {
		return nil, nil, errors.New("profile group is not selectable")
	}
	for _, group := range e.profile.raw.ProxyGroup {
		if group["name"] != name || group["type"] != "select" {
			continue
		}
		p := e.current.Proxies[name]
		if p != nil {
			if selector, ok := originalAdapter(p).(*outboundgroup.Selector); ok {
				return group, selector, nil
			}
		}
	}
	return nil, nil, errors.New("profile group is not selectable")
}

// GroupChoices wakes an idle core explicitly and returns this group's bounded
// members. Auto-test/fallback/load-balance groups remain owned by the profile.
func (e *Engine) GroupChoices(name string) (string, error) {
	if !safeName(name) {
		return "", errors.New("invalid group name")
	}
	if err := e.Prepare(); err != nil {
		return "", err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	group, selector, err := e.selectableGroupLocked(name)
	if err != nil {
		return "", err
	}
	raw, err := json.Marshal(map[string]any{"group": name, "selected": selector.Now(), "choices": groupChoices(group)})
	return string(raw), err
}

// SelectGroup preserves subscription rules and only changes an explicit select
// member. Existing node-selection safety gates also apply to profile groups.
func (e *Engine) SelectGroup(name, choice string) error {
	if !safeName(name) || !safeName(choice) {
		return errors.New("invalid group selection")
	}
	if err := e.Prepare(); err != nil {
		return err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.active != 0 || e.phoneVPNActive() {
		return errors.New("finish active connections before changing group selection")
	}
	group, selector, err := e.selectableGroupLocked(name)
	if err != nil {
		return err
	}
	if !containsGroupChoice(group, choice) {
		return errors.New("choice is not a member of this policy group")
	}
	if err := selector.Set(choice); err != nil {
		return errors.New("policy group rejected this choice")
	}
	if e.groupSelections == nil {
		e.groupSelections = map[string]string{}
	}
	e.groupSelections[name] = choice
	e.lastUsed = time.Now()
	return nil
}
