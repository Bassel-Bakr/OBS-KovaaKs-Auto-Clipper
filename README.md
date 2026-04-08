# Python Project

Welcome to your Python project!

## Getting Started

1. **Clone the repository:**

   ```bash
   git clone https://github.com/Bassel-Bakr/OBS-KovaaKs-Auto-Clipper.git
   cd OBS-KovaaKs-Auto-Clipper
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

We'll need to set up credentials in OBS Studio:

1. Open OBS Studio and go to `Tools` > `WebSocket Server Settings`.
1. Enable the WebSocket server.
1. Set a server port (default is `4455`).
1. Optionally, set a password for added security.
1. Save your settings.

Before running the app, update the `config.json` file with your OBS WebSocket password:

1. Open the `config.json` file in the project directory.
2. Locate the `"obs_password"` field.
3. Set its value to the password you configured in OBS WebSocket settings. For example:

   ```json
   {
     "obs_password": "your_password_here"
   }
   ```

4. Save the file.

## Usage

```bash
python app.py
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](LICENSE)
