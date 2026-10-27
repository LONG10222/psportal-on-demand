"""Local presentation preferences; Windows personalization is read-only."""
import colorsys
import re
import sys

THEMES = ('system', 'dark', 'light', 'custom')

def valid_color(value):
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None

def rgb(color):
    return tuple(int(color[i:i+2], 16)/255 for i in (1,3,5))

def color(values):
    return '#' + ''.join(f'{round(max(0,min(1,c))*255):02x}' for c in values)

def blend(a,b,amount):
    return color(x*(1-amount)+y*amount for x,y in zip(rgb(a),rgb(b)))

def luminance(value):
    channels=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in rgb(value)]
    return sum(c*w for c,w in zip(channels,(.2126,.7152,.0722)))

def ink(value):
    return '#ffffff' if (luminance(value)+.05)/.05 < 1.05/(luminance(value)+.05) else '#000000'

def system_colors():
    light=False; accent='#7863d7'
    if sys.platform=='win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                light=bool(winreg.QueryValueEx(key,'AppsUseLightTheme')[0])
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\DWM') as key:
                value=winreg.QueryValueEx(key,'ColorizationColor')[0]
                if type(value) is int:accent=f'#{value & 0xffffff:06x}'
        except OSError:pass
    return ('#f4f5f9' if light else '#121520'),accent

def palette(theme,custom='#182333'):
    base,accent=system_colors() if theme=='system' else ('#111326','#7863d7') if theme=='dark' else ('#f4f2fc','#6250b9')
    if theme=='custom':
        base=custom if valid_color(custom) else '#182333'
        hue,sat,_=colorsys.rgb_to_hsv(*rgb(base))
        accent=color(colorsys.hsv_to_rgb(hue if sat>.12 else .70,.58,.94 if luminance(base)<.3 else .56))
    dark=luminance(base)<.3
    card=blend(base,'#ffffff',.07 if dark else .85)
    if abs(luminance(accent)-luminance(card))<.12:accent=blend(accent,'#ffffff' if dark else '#000000',.4)
    gray=color([sum(rgb(card))/3]*3)
    return dict(page=base,side=blend(base,'#000000',.18 if dark else .04),card=card,
        text=ink(card),note=blend(ink(card),card,.25),
        entry=blend(base,'#000000',.12) if dark else '#ffffff',edge=blend(card,'#ffffff' if dark else '#000000',.18),
        selected=accent,selected_text=ink(accent),hover=blend(accent,card,.65),button=blend(card,accent,.10),
        accent=accent,accent_text=ink(accent),status=blend(accent,'#ffffff' if dark else '#000000',.4),
        accent_hover=blend(accent,'#ffffff' if dark else '#000000',.15),scroll=blend(card,accent,.4),
        disabled=blend(gray,base,.15),disabled_text='#838994' if dark else '#89909c')
