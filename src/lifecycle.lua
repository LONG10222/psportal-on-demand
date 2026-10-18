-- Pure state machine: service work runs outside the listener event loop.
local M = {}
function M.new(timeout, idle)
    return {state='off', timeout=timeout, idle=idle, last_activity=0}
end
function M.request(self, now)
    if self.state == 'ready' then self.last_activity=now; return 'ready' end
    if self.state == 'starting' then return 'wait' end
    self.state='starting'; self.deadline=now+self.timeout
    return 'start'
end
function M.complete(self, now, success)
    self.state=success and 'ready' or 'off'
    -- Startup time must never consume the first request's idle budget.
    self.last_activity=now; self.deadline=nil
end
function M.expired(self, now)
    return self.state=='starting' and now>=self.deadline
end
function M.active(self, now) self.last_activity=now end
function M.should_stop(self, now, pending)
    return self.state~='starting' and not pending and now-self.last_activity>=self.idle
end
return M
