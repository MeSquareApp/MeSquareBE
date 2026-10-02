# MeSquareBE

Run 
```bash
uv add uvicorn
```
Start your Docker app, then run this command:
```bash
docker compose up --build
```

If you want to run app locally with no docker, just run these 2 commands
```bash
uv sync
uv run fastapi dev
```

Once app runs, go to this link: http://localhost:8000/

For documentation, go to this link: http://localhost:8000/docs
