from google_auth_oauthlib.flow import InstalledAppFlow
import pickle
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRET_PATH = Path("~/Code/python/live-merge-up/credentials/client_secret.json").expanduser()
TOKEN_PATH = Path("token.pickle")

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
creds = flow.run_local_server(port=0)

with open(TOKEN_PATH, "wb") as token_file:
    pickle.dump(creds, token_file)

print("token.pickle 文件生成成功！请上传到服务器使用。")
