
import base64
import json

def xor_decode(encrypted_data, xor_password="lok"):
    """Decode XOR encrypted data using the same method as in client.py"""
    return bytearray([
        each_encrypted ^ ord(xor_password[index % len(xor_password)])
        for index, each_encrypted in enumerate(encrypted_data)
    ])

def decode_message(encoded_string):
    """Decode the Base64 XOR encrypted message"""
    try:
        # Decode from Base64
        encrypted_data = base64.b64decode(encoded_string)
        
        # XOR decode with the default password "lok"
        decrypted_data = xor_decode(encrypted_data)
        
        # Try to parse as JSON
        try:
            result = json.loads(decrypted_data.decode('utf-8'))
            return result
        except json.JSONDecodeError:
            # If not JSON, return as string
            return decrypted_data.decode('utf-8')
            
    except Exception as e:
        return f"Error decoding: {str(e)}"

if __name__ == "__main__":
    encoded_message = "VRQKVUJACBJFA0BEF0sCFBxZQkEFCARcFgxRHBkaWkRDWgsWFBsObRkMTVkcVRMPUVZWCQQEUh8CFBldXkAKEkUDAAZSAgxpEVQTD0ZQUF0DUwZMGVdNBgBUXQAFAVIAB0geVUgSTBkfRARWUFNAFBsGSQABBFRXSxtVWw1bQEJaCgYFVEpFZl1SQBQMAE9UBlAABFBYAQBTTxdQGghXAwEAV19WFB8CVRQbX1VQRlxSCQUGUh0eB1QSUFgLEwlNFgxbHh4aWm9YUUZcRQ8DUlVLSlRAUQQDVQdeX1YOBBhIB0oGBBcZShwbV1kGSwwMTQAABVRXVwsYFANDQUMWRBMPUVVXCw0aQHFHUloKEwNTAwULDARXF0xVTFIHUwIDUw5QUlcXFhQFHEoXBwkDXBYMVx4fBkgDAQdIRAZUW0MMWgwMTAUIDVFKRWZdUkAUDABPVVQCVAJUWAEOWhscAUwCBVFdBVQJURQfAlUUG19VUEZcUgkFBlIcHgRUElBYCxMJTRYMUxoZBUAcE2oNAkUDFgBVS0sBQAIFDVVUXwwMVFEYSlROUldQV0QaZBgUEU9YUyxCXloUFUUDb20ZDE1ZHFUTD1FWVgkEBVIcAhQZXV5AChJFAwADUh4CFAtVXVAHEkUDBBpAcUdSWgoTA1MAUw9RBVMfGlVABFIGU1NSXwBUWhlMFAVtHW45SjxkGG0ZDE1ZHFUTD1FWVgkEBVIcAhQZXV5AChJFAwEGUgIMRR1cVFYQRF0JGBQ9R0oUQhIHAgEDAQoMB1JKSlIaAwZWBlRXDgEDBhgMSyVtHRcJBxVaXGIbXksUQgEdFwIJRQNPFD1HShRCEgcNUwdWWwMFVRwaB0kEVAwHBVcOUlVVTwwaWlxeVkZcPA8FGlMeGwNUAQQEVDtLG1hTFEtCFEIEHRcHCQNcFgxQHh8GSAEBAUhEF1hGVw8MFE1aRlBZEQNFAwcGUh4eBgUcE0YQBxNcFgxTAgxTAEBYRwECRQMWBFIcGxtIBxwHVDJXCA4HVhQcBFYACQM"
    
    result = decode_message(encoded_message)
    print("Decoded message:")
    print(json.dumps(result, indent=2) if isinstance(result, dict) else result)
