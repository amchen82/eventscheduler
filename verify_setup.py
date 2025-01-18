from secure_config import SecureConfig
import os

def verify_setup():
    print("Verifying secure configuration setup...")
    
    # Check for required files
    files_check = {
        '.key': 'Encryption key file',
        '.env.encrypted': 'Encrypted credentials file'
    }
    
    for file, description in files_check.items():
        if os.path.exists(file):
            print(f"✓ {description} found ({file})")
        else:
            print(f"✗ {description} missing ({file})")
            return False
    
    # Check if .env file is absent (as it should be)
    if os.path.exists('.env'):
        print("✗ Plain text .env file still exists - should be deleted")
        return False
    else:
        print("✓ No plain text .env file present")
    
    # Try to read credentials
    try:
        config = SecureConfig()
        email_pwd = config.get_secret('EMAIL_PASSWORD')
        api_key = config.get_secret('GEMINI_API_KEY')
        
        if email_pwd and api_key:
            print("✓ Successfully decrypted credentials")
            print(f"✓ Email password length: {len(email_pwd)} characters")
            print(f"✓ Gemini API key length: {len(api_key)} characters")
        else:
            print("✗ Failed to retrieve credentials")
            return False
            
        # Check file permissions on .key file
        key_permissions = oct(os.stat('.key').st_mode)[-3:]
        if key_permissions == '400':
            print("✓ Key file has correct permissions (400)")
        else:
            print(f"✗ Key file has incorrect permissions ({key_permissions})")
            
    except Exception as e:
        print(f"✗ Error during verification: {str(e)}")
        return False
    
    print("\nVerification complete! Setup appears to be working correctly.")
    return True

if __name__ == "__main__":
    verify_setup() 