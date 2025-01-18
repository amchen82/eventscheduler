from cryptography.fernet import Fernet
import os
import base64
import getpass

class SecureConfig:
    def __init__(self, key_file='.key'):
        self.key_file = key_file
        self.key = self._load_or_generate_key()
        self.cipher_suite = Fernet(self.key)
    
    def _load_or_generate_key(self):
        if os.path.exists(self.key_file):
            # Set file permissions to owner read-only
            os.chmod(self.key_file, 0o400)
            with open(self.key_file, 'rb') as key_file:
                return key_file.read()
        else:
            key = Fernet.generate_key()
            with open(self.key_file, 'wb') as key_file:
                key_file.write(key)
            # Set file permissions to owner read-only
            os.chmod(self.key_file, 0o400)
            return key
    
    def encrypt_env(self):
        if not os.path.exists('.env'):
            raise FileNotFoundError('.env file not found')
            
        # Read current .env
        with open('.env', 'r') as file:
            env_contents = file.read()
        
        # Encrypt contents
        encrypted = self.cipher_suite.encrypt(env_contents.encode())
        
        # Save encrypted contents
        with open('.env.encrypted', 'wb') as file:
            file.write(encrypted)
        
        print("Environment variables encrypted. Original .env file can now be deleted.")
    
    def decrypt_env(self):
        if not os.path.exists('.env.encrypted'):
            raise FileNotFoundError('.env.encrypted file not found')
            
        # Read encrypted file
        with open('.env.encrypted', 'rb') as file:
            encrypted_contents = file.read()
            
        # Decrypt contents
        decrypted = self.cipher_suite.decrypt(encrypted_contents).decode()
        
        return dict(line.split('=', 1) for line in decrypted.splitlines() if line.strip())

    def get_secret(self, key):
        env_vars = self.decrypt_env()
        value = env_vars.get(key, '')
        return value.strip("'").strip('"') if value else '' 

    @staticmethod
    def initial_setup():
        """Interactive setup for initial credentials"""
        print("Setting up secure credentials...")
        email_pwd = getpass.getpass("Enter EMAIL_PASSWORD: ")
        gemini_key = getpass.getpass("Enter GEMINI_API_KEY: ")
        
        env_contents = f"""EMAIL_PASSWORD='{email_pwd}'
GEMINI_API_KEY='{gemini_key}'"""
        
        # Write temporary .env file
        with open('.env', 'w') as f:
            f.write(env_contents)
        
        # Create instance and encrypt
        config = SecureConfig()
        config.encrypt_env()
        
        # Remove temporary .env file
        os.remove('.env')
        print("\nCredentials encrypted successfully!")
        print("The .env file has been encrypted and removed.")
        print("IMPORTANT: Keep the .key file secure and backup both .key and .env.encrypted files") 