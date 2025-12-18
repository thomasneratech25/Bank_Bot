            # Read All KMA Bank Messages
            print("🤖 Reading latest message from KMA bank...")

            # Read All KMA Messages
            message_nodes = poco("message_list").offspring("message_text")

            # --- Collect OTP + Ref from all new messages ---
            otp_candidates = []
            for i, node in reversed(list(enumerate(message_nodes))):
                messages = node.get_text().strip()
                if not messages:
                    continue
                
                # using regex to get Message OTP Code and Ref Code
                match = re.search(r"\bRef\s*[:\-]?\s*(\d+)\b.*?\bOTP\s*[:\-]?\s*(\d+)\b", messages, re.IGNORECASE,)

                if match:
                    _messages_ref_code, messages_otp_code = match.groups()
                    otp_candidates.append((_messages_ref_code.strip(), messages_otp_code.strip()))
                    print(f"# Ref: {_messages_ref_code}, OTP: {messages_otp_code} ❌")

            # --- Match correct Ref Code ---
            for _messages_ref_code, messages_otp_code in otp_candidates:
                if cls._kma_ref == _messages_ref_code:
                    print(f"Found matching Ref: {_messages_ref_code} | OTP: {messages_otp_code} ✅")
                    return messages_otp_code
                
            # If no match, loop again
            print("# OTP not found yet, keep waiting... \n")


    job = {
    "deviceId": data["deviceId"],
    "merchantCode": data["merchantCode"],
    "fromBankCode": data["fromBankCode"],
    "fromAccountName": data["fromAccountNum"],
    "toBankCode": data["toBankCode"],
    "toAccountNum": data["toAccountNum"],
    "toAccountName": data["toAccountName"],
    "amount": data["amount"],
    "username": data["username"],
    "password": data["password"],
    "pin": data["pin"],
    "transactionId": data["transactionId"],
    "status": "pending",
    "createdAt": datetime.utcnow().isoformat()
    }



{   
    "deviceId": "2312",
    "merchantCode": "IBS",
    "fromBankCode": "SCB Company Web",
    "fromAccountNum": "8144211935",
    "toBankCode": "Krungsri",
    "toAccountNum": "2651424765",
    "toAccountName": "VIVIEN LIVE MALL CO LTD",
    "amount": "100",
    "username": "JIN666",
    "password": "Aaaa1111@",
    "pin": "",
    "transactionId": "8813"
}

{   
    "deviceId": "2312",
    "merchantCode": "IBS",
    "fromBankCode": "TTB Company Web",
    "fromAccountNum": "4272987647",
    "toBankCode": "Siam Commercial Bank Public Company Limited",
    "toAccountNum": "8144211935",
    "toAccountName": "THAI SURE TRANSPORT CO. LTD",
    "amount": "100",
    "username": "wanneeboo086",
    "password": "Ozone112233@",
    "pin": "",
    "transactionId": "1111"
}