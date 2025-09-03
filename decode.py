
import base64
import json

def xor(plain: bytes, xor_password: str) -> bytes:
    return bytearray([
        each_plain ^ ord(xor_password[index % len(xor_password)])
        for index, each_plain in enumerate(plain)
    ])

def b64xor_dec(s: str, xor_password: str) -> dict:
    return json.loads(xor(base64.b64decode(s), xor_password))

if __name__ == '__main__':
    # Get inputs from user
    response = input("Enter the encoded response: ")
    password = input("Enter the XOR password: ")
    
    try:
        # Decode and print result
        decoded = b64xor_dec(response, password)
        print("\nDecoded response:")
        print(json.dumps(decoded, indent=2))
    except Exception as e:
        print(f"\nError decoding: {str(e)}")
