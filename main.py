from backend.app import create_app
import os
from dotenv import load_dotenv

load_dotenv()

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3006))
    app.run(debug=True, host='0.0.0.0', port=port)
