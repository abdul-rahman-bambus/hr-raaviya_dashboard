from datetime import datetime, timedelta
import pytz

def calculate_checkout_utc(check_in_utc, tz_name, hour_to_float):
    tz = pytz.timezone(tz_name)
    check_in_local = check_in_utc.astimezone(tz)
    
    hours = int(hour_to_float)
    minutes = int((hour_to_float - hours) * 60)
    
    checkout_local = check_in_local.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    
    if checkout_local < check_in_local:
        checkout_local += timedelta(days=1)
        
    checkout_utc = checkout_local.astimezone(pytz.utc).replace(tzinfo=None)
    return checkout_utc

ci = datetime.utcnow().replace(tzinfo=pytz.utc)
print("Check In:", ci)
co = calculate_checkout_utc(ci, 'Asia/Kolkata', 18.5)
print("Check Out:", co)
