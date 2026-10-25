'use strict';
'require baseclass';

return baseclass.extend({
    create: function(now) {
        now = now || function() { return performance.now(); };
        var sample = null, anchor = 0, initialAge = 0;
        function valid(value) { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0; }
        return {
            reset: function() { sample = null; },
            accept: function(value) {
                if (!value || !valid(value.updated_at) || !valid(value.remaining_seconds)) return;
                if (sample && value.updated_at < sample.updated_at) return;
                if (sample && value.updated_at === sample.updated_at &&
                    value.pause_state === sample.pause_state && value.remaining_seconds === sample.remaining_seconds) return;
                sample = Object.assign({}, value);
                anchor = now();
                initialAge = valid(value.sample_age_seconds) ? value.sample_age_seconds : 0;
            },
            read: function() {
                if (!sample) return null;
                var elapsed = (Number.isFinite(Number(sample.pause_state)) && Number(sample.pause_state) > 0) ?
                    initialAge + Math.max(0, Math.floor((now() - anchor) / 1000)) : 0;
                return { seconds: Math.max(0, sample.remaining_seconds - elapsed),
                    estimated: (Number.isFinite(Number(sample.pause_state)) && Number(sample.pause_state) > 0) };
            }
        };
    }
});
