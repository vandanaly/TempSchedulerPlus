# TempSchedPlus
URL: https://tempschedplus-dashboard.onrender.com/

Intelligent temperature-aware storage management across device, edge, and cloud.

## Project Objectives
1. **Cold Data Compression**: Reduces storage space using algorithms like GZIP or Zstandard before archival.
2. **Advanced AI Prediction**: Uses Transformer-based ML models to forecast temperature trends and access patterns.
3. **Real-Time Adaptive Scheduling**: Dynamically adjusts Hot/Cold boundaries based on real-time conditions rather than fixed thresholds.
4. **Security (Encryption)**: Protects stored data using robust symmetric encryption before storage.
5. **Auto Parameter Tuning**: Automatically optimizes scheduling intervals and temperature thresholds.

## Cloud Deployment Architecture

Because TempSchedPlus consists of a long-running FastAPI backend and a Streamlit frontend, you must deploy them as **two separate web services** on platforms like Render.

### 1. Deploy the Backend (FastAPI)
Run the backend API and background scheduler loop:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
