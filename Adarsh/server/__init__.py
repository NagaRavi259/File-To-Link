# © agrprojects
import csv
import os
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from .stream_routes import router

# Define the path for the CSV file
log_file_path = "logs/request_logs.csv"

# Ensure the CSV file has the correct headers if it doesn't exist
if not os.path.exists(log_file_path):
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    with open(log_file_path, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Timestamp", "IP Address", "Endpoint"])

# Initialize FastAPI app
app = FastAPI(docs_url=None, redoc_url=None)

# Middleware for request logging
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    # Capture the details
    timestamp = datetime.utcnow().isoformat()
    ip_address = request.client.host
    endpoint = str(request.url)

    # Log to the CSV file
    with open(log_file_path, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([timestamp, ip_address, endpoint])

    # Call the next middleware/handler
    response = await call_next(request)
    return response

# Define the route to serve the favicon.ico
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Adjust the file path to where your favicon.ico is located
    return FileResponse("Adarsh/favicon.ico")

# Include routes from stream_routes
app.include_router(router)
