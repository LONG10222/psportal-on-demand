// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"strings"
	"sync"
)

type runtimeCommand struct {
	Command           string `json:"command"`
	RequestID         int    `json:"request_id"`
	SelectionMode     string `json:"selection_mode"`
	PreferredNode     string `json:"preferred_node"`
	SwitchThresholdMS *int   `json:"switch_threshold_ms"`
}

type runtimeEngine interface {
	Status() string
	Prepare() error
	TestNodes() error
	SelectNode(string, string) error
	SelectNodeWithThreshold(string, string, int) error
}

type runtimeControl struct {
	app           runtimeEngine
	output        io.Writer
	mu            sync.Mutex
	outputMu      sync.Mutex
	busy          bool
	lastCommandID int
	commandError  string
}

func parseCommand(line string) (runtimeCommand, error) {
	var value runtimeCommand
	if len(line) > 4096 {
		return value, errors.New("runtime command too large")
	}
	decoder := json.NewDecoder(strings.NewReader(line))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return value, err
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return value, errors.New("expected one runtime command")
	}
	if value.RequestID < 0 || value.RequestID > 2147483647 {
		return value, errors.New("invalid request ID")
	}
	switch value.Command {
	case "status", "prepare", "test", "select":
	default:
		return value, errors.New("unsupported runtime command")
	}
	return value, nil
}
func (c *runtimeControl) publish() {
	c.outputMu.Lock()
	defer c.outputMu.Unlock()
	var status map[string]any
	if json.Unmarshal([]byte(c.app.Status()), &status) != nil {
		return
	}
	c.mu.Lock()
	status["busy"], status["last_command_id"], status["command_error"] = c.busy, c.lastCommandID, c.commandError
	c.mu.Unlock()
	output := c.output
	if output == nil {
		output = os.Stdout
	}
	encoder := json.NewEncoder(output)
	encoder.SetEscapeHTML(false)
	_ = encoder.Encode(status)
}
func (c *runtimeControl) accept(line string) {
	value, err := parseCommand(line)
	if err != nil {
		c.mu.Lock()
		c.commandError = "Invalid runtime command"
		c.mu.Unlock()
		c.publish()
		return
	}
	if value.Command == "status" {
		c.publish()
		return
	}
	c.mu.Lock()
	if c.busy {
		c.lastCommandID, c.commandError = value.RequestID, "A node operation is already in progress"
		c.mu.Unlock()
		c.publish()
		return
	}
	c.busy, c.commandError = true, ""
	c.mu.Unlock()
	c.publish()
	go func() {
		var err error
		switch value.Command {
		case "prepare":
			err = c.app.Prepare()
		case "test":
			err = c.app.TestNodes()
		case "select":
			if value.SwitchThresholdMS != nil {
				err = c.app.SelectNodeWithThreshold(value.SelectionMode, value.PreferredNode, *value.SwitchThresholdMS)
			} else {
				err = c.app.SelectNode(value.SelectionMode, value.PreferredNode)
			}
		}
		c.mu.Lock()
		c.busy, c.lastCommandID, c.commandError = false, value.RequestID, ""
		// Engine errors are deliberately sanitized at the network boundary.
		if err != nil {
			c.commandError = err.Error()
		}
		c.mu.Unlock()
		c.publish()
	}()
}
