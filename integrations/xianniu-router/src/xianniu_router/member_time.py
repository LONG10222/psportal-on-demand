"""Official duration counters, kept separate from the membership expiry date."""
import re


def seconds(value):
    if isinstance(value,bool):return None
    if isinstance(value,str):
        if not re.fullmatch(r'\d{1,15}',value):return None
        value=int(value)
    if not isinstance(value,(int,float)) or not 0<=value<=9007199254740991:return None
    if int(value)!=value:return None
    return int(value)


def balances(member):
    # total_datetime was observed decreasing by 188 for 188 elapsed seconds
    # while official timing was active. Never add free_datetime to it: the
    # vendor's consumption/overlap rules are not part of this projection.
    return {'remaining_seconds':seconds(member.get('total_datetime')),
            'trial_seconds':seconds(member.get('free_datetime')),
            'time_unit':'seconds'}
