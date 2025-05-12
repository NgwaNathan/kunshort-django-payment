def clean_phone_number(phone_number: str, prefx = "237") -> str:
    if phone_number.startswith(prefx):
        return phone_number[3:]
    if phone_number.startswith(f"+{prefx}"):
        return phone_number[4:]
    
    return phone_number