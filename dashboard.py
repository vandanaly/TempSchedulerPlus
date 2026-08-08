from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import uuid

import streamlit as st

import cold_pipeline
import config
import supabase_backend as cloud_backend
import prediction
import scheduler


st.set_page_config(page_title="TempSched+ Control Deck", page_icon="◢", layout="wide")


def _auth_username():
	return os.environ.get("TEMPSCHED_USERNAME", "admin")


def _auth_password():
	return os.environ.get("TEMPSCHED_PASSWORD", "tempschedplus")


def _is_authenticated():
	return bool(st.session_state.get("authenticated"))


def _login_page():
	st.markdown(
		"""
		<div class="hero">
			<div class="hero-grid">
				<div class="hero-copy">
					<div class="hero-kicker">Secure Access</div>
					<h1>TempSched+ Login</h1>
					<p>Authenticate before entering the storage control plane. The dashboard stays hidden until valid credentials are provided.</p>
				</div>
				<div class="signal-card">
					<div class="signal-title">Protected Session</div>
					<div class="signal-value">Authentication Required</div>
					<div class="signal-caption">Use the credential pair configured in environment variables to unlock the dashboard.</div>
				</div>
			</div>
		</div>
		""",
		unsafe_allow_html=True,
	)
	left, right = st.columns([1.1, 0.9])
	with left:
		with st.form("login_form", clear_on_submit=False):
			st.markdown("<div class='panel-card'><div class='tier-title'>Sign in</div><div class='small-note'>Default local credentials are provided for development, but you can override them with environment variables.</div></div>", unsafe_allow_html=True)
			username = st.text_input("Username", placeholder="Enter username")
			password = st.text_input("Password", type="password", placeholder="Enter password")
			submitted = st.form_submit_button("Log in", use_container_width=True)
			if submitted:
				if username == _auth_username() and password == _auth_password():
					st.session_state["authenticated"] = True
					st.session_state["login_error"] = ""
					st.rerun()
				else:
					st.session_state["login_error"] = "Invalid username or password."
		if st.session_state.get("login_error"):
			st.error(st.session_state["login_error"])
	with right:
		st.markdown(
			"""
			<div class='panel-card'>
				<div class='tier-title'>Development credentials</div>
				<div class='small-note'>
					Set <code>TEMPSCHED_USERNAME</code> and <code>TEMPSCHED_PASSWORD</code> before starting the app to replace the defaults.
				</div>
				<div class='subtle-divider'></div>
				<div class='small-note'>
					This gate is session-based and keeps the dashboard hidden until login succeeds.
				</div>
			</div>
			""",
			unsafe_allow_html=True,
		)


if "authenticated" not in st.session_state:
	st.session_state["authenticated"] = False

if not _is_authenticated():
	_login_page()
	st.stop()


def _list_files(path: Path):
	return sorted([item.name for item in path.iterdir() if item.is_file()])


def _count_bytes(path: Path):
	return sum(item.stat().st_size for item in path.iterdir() if item.is_file())


def _session_id():
	if "session_id" not in st.session_state:
		st.session_state["session_id"] = uuid.uuid4().hex
	return str(st.session_state["session_id"])


def _upload_staging_dir():
	staging_dir = config.UPLOADS / _session_id()
	staging_dir.mkdir(parents=True, exist_ok=True)
	return staging_dir


def _save_uploaded_files(uploaded_files):
	saved_paths = []
	staging_dir = _upload_staging_dir()
	for index, uploaded_file in enumerate(uploaded_files, start=1):
		safe_name = Path(uploaded_file.name).name
		target_path = staging_dir / f"{index:03d}_{safe_name}"
		target_path.write_bytes(uploaded_file.getbuffer())
		saved_paths.append(target_path)
	return saved_paths


def _active_scan_paths():
	staging_dir = _upload_staging_dir()
	if staging_dir.exists() and any(staging_dir.iterdir()):
		return [staging_dir]
	return list(getattr(config, "SCAN_PATHS", []))


def _uploaded_device_files():
	staging_dir = _upload_staging_dir()
	if not staging_dir.exists():
		return []
	return sorted([path for path in staging_dir.iterdir() if path.is_file()])


def _render_metric(label, value, caption):
	st.markdown(
		f"""
		<div class="metric-card">
			<div class="metric-label">{label}</div>
			<div class="metric-value">{value}</div>
			<div class="metric-caption">{caption}</div>
		</div>
		""",
		unsafe_allow_html=True,
	)


def _load_recent_action_events(limit=3000):
	action_log = config.LOGS / "actions.jsonl"
	if not action_log.exists():
		return []
	try:
		lines = action_log.read_text(encoding="utf-8").splitlines()[-int(limit):]
	except OSError:
		return []

	events = []
	for line in lines:
		text = str(line).strip()
		if not text:
			continue
		try:
			events.append(json.loads(text))
		except json.JSONDecodeError:
			continue
	return events


def _access_stats_30d(file_path: Path):
	now = datetime.now(timezone.utc)
	cutoff = now.timestamp() - (30 * 24 * 3600)
	events = _load_recent_action_events()

	count = 0
	for item in events:
		filename = str(item.get("filename", ""))
		timestamp_text = str(item.get("timestamp", "")).strip()
		if filename != file_path.name:
			continue
		if not timestamp_text:
			continue
		if timestamp_text.endswith("Z"):
			timestamp_text = timestamp_text[:-1] + "+00:00"
		try:
			event_dt = datetime.fromisoformat(timestamp_text)
		except ValueError:
			continue
		if event_dt.tzinfo is None:
			event_dt = event_dt.replace(tzinfo=timezone.utc)
		if event_dt.timestamp() >= cutoff:
			count += 1

	return {
		"past_30d_accesses": int(count),
		"avg_daily_accesses": round(float(count) / 30.0, 2),
	}


st.markdown(
	"""
	<style>
		:root {
			--bg-deep: #050816;
			--bg-surface: rgba(10, 14, 30, 0.76);
			--bg-surface-strong: rgba(13, 18, 38, 0.92);
			--line-soft: rgba(132, 148, 170, 0.18);
			--line-strong: rgba(125, 211, 252, 0.26);
			--text-main: #e2e8f0;
			--text-muted: #94a3b8;
			--accent: #22d3ee;
			--accent-2: #38bdf8;
			--accent-3: #a78bfa;
			--success: #34d399;
			--warn: #f59e0b;
		}
		.stApp {
			background:
				radial-gradient(circle at 14% 18%, rgba(34, 211, 238, 0.16), transparent 18%),
				radial-gradient(circle at 82% 12%, rgba(167, 139, 250, 0.18), transparent 22%),
				radial-gradient(circle at 68% 78%, rgba(56, 189, 248, 0.10), transparent 25%),
				linear-gradient(160deg, #030712 0%, #07111f 52%, #0a1224 100%);
			color: var(--text-main);
		}
		.stApp::before {
			content: "";
			position: fixed;
			inset: 0;
			pointer-events: none;
			background-image:
				linear-gradient(rgba(148, 163, 184, 0.05) 1px, transparent 1px),
				linear-gradient(90deg, rgba(148, 163, 184, 0.05) 1px, transparent 1px);
			background-size: 54px 54px;
			mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.65), transparent 94%);
			-webkit-mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.65), transparent 94%);
		}
		.block-container {
			padding-top: 1.1rem;
			padding-bottom: 2rem;
			max-width: 1480px;
		}
		.hero {
			position: relative;
			overflow: hidden;
			padding: 1.6rem 1.7rem 1.45rem;
			border-radius: 28px;
			background:
				linear-gradient(135deg, rgba(8, 15, 31, 0.96), rgba(8, 30, 58, 0.92) 48%, rgba(20, 48, 92, 0.88));
			border: 1px solid rgba(148, 163, 184, 0.16);
			box-shadow: 0 24px 90px rgba(3, 7, 18, 0.5);
			margin-bottom: 1rem;
		}
		.hero::after {
			content: "";
			position: absolute;
			inset: -20% -10% auto auto;
			width: 240px;
			height: 240px;
			background: radial-gradient(circle, rgba(34, 211, 238, 0.28), transparent 68%);
			filter: blur(4px);
			pointer-events: none;
		}
		.hero-grid {
			display: grid;
			grid-template-columns: 1.7fr 1fr;
			gap: 1rem;
			align-items: start;
			position: relative;
			z-index: 1;
		}
		.hero-kicker {
			display: inline-flex;
			align-items: center;
			gap: 0.45rem;
			padding: 0.36rem 0.75rem;
			border-radius: 999px;
			background: rgba(34, 211, 238, 0.12);
			border: 1px solid rgba(34, 211, 238, 0.22);
			color: #9fefff;
			font-size: 0.78rem;
			letter-spacing: 0.14em;
			text-transform: uppercase;
			font-weight: 700;
		}
		.hero h1 {
			margin: 0.75rem 0 0;
			font-size: clamp(2.1rem, 4vw, 3.6rem);
			line-height: 0.98;
			letter-spacing: -0.055em;
		}
		.hero p {
			margin: 0.8rem 0 0;
			max-width: 820px;
			color: #cbd5e1;
			font-size: 1rem;
			line-height: 1.6;
		}
		.hero-copy {
			padding-right: 0.4rem;
		}
		.hero-badges {
			display: flex;
			flex-wrap: wrap;
			gap: 0.55rem;
			margin-top: 1rem;
		}
		.chip {
			display: inline-flex;
			align-items: center;
			gap: 0.4rem;
			padding: 0.42rem 0.72rem;
			border-radius: 999px;
			background: rgba(15, 23, 42, 0.52);
			border: 1px solid rgba(148, 163, 184, 0.16);
			color: #dbeafe;
			font-size: 0.8rem;
			font-weight: 600;
		}
		.signal-card {
			background: linear-gradient(180deg, rgba(15, 23, 42, 0.74), rgba(2, 6, 23, 0.78));
			border: 1px solid rgba(125, 211, 252, 0.18);
			border-radius: 22px;
			padding: 1rem 1.05rem;
			box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
		}
		.signal-title {
			font-size: 0.78rem;
			text-transform: uppercase;
			letter-spacing: 0.16em;
			color: #7dd3fc;
			margin-bottom: 0.4rem;
		}
		.signal-value {
			font-size: 1.55rem;
			font-weight: 800;
			letter-spacing: -0.04em;
			color: #f8fafc;
		}
		.signal-caption {
			margin-top: 0.25rem;
			font-size: 0.9rem;
			color: var(--text-muted);
		}
		.metric-card, .panel-card {
			background: linear-gradient(180deg, rgba(13, 18, 38, 0.88), rgba(7, 11, 24, 0.94));
			border: 1px solid var(--line-soft);
			border-radius: 22px;
			padding: 1rem 1.05rem;
			box-shadow: 0 18px 46px rgba(2, 6, 23, 0.35);
			backdrop-filter: blur(14px);
		}
		.metric-card:hover, .panel-card:hover, .signal-card:hover {
			border-color: var(--line-strong);
			transform: translateY(-1px);
			transition: 180ms ease;
		}
		.metric-label {
			font-size: 0.74rem;
			text-transform: uppercase;
			letter-spacing: 0.16em;
			color: var(--text-muted);
		}
		.metric-value {
			font-size: 1.95rem;
			font-weight: 800;
			margin-top: 0.25rem;
			color: #f8fafc;
			letter-spacing: -0.05em;
		}
		.metric-caption {
			font-size: 0.9rem;
			color: var(--text-muted);
			margin-top: 0.25rem;
		}
		.tier-title {
			font-size: 1.02rem;
			font-weight: 800;
			margin-bottom: 0.5rem;
			color: #f8fafc;
			letter-spacing: -0.02em;
		}
		.file-pill {
			display: inline-block;
			padding: 0.34rem 0.7rem;
			margin: 0.15rem 0.2rem 0.15rem 0;
			border-radius: 999px;
			background: rgba(34, 211, 238, 0.1);
			color: #8ee7ff;
			font-size: 0.8rem;
			border: 1px solid rgba(34, 211, 238, 0.22);
		}
		.section-title {
			margin: 1.15rem 0 0.7rem;
			font-size: 0.92rem;
			font-weight: 800;
			letter-spacing: 0.18em;
			text-transform: uppercase;
			color: #93c5fd;
		}
		.small-note {
			color: var(--text-muted);
			font-size: 0.9rem;
			line-height: 1.5;
		}
		[data-testid="stSidebar"] {
			background: linear-gradient(180deg, rgba(5, 8, 22, 0.96), rgba(9, 14, 28, 0.98));
			border-right: 1px solid rgba(125, 211, 252, 0.12);
		}
		[data-testid="stSidebar"] .stButton > button {
			border-radius: 14px;
			border: 1px solid rgba(34, 211, 238, 0.24);
			background: linear-gradient(135deg, rgba(34, 211, 238, 0.18), rgba(56, 189, 248, 0.12));
			color: #ecfeff;
			font-weight: 700;
			padding: 0.7rem 0.95rem;
		}
		[data-testid="stSidebar"] .stButton > button:hover {
			border-color: rgba(34, 211, 238, 0.42);
			background: linear-gradient(135deg, rgba(34, 211, 238, 0.28), rgba(56, 189, 248, 0.22));
		}
		.status-line {
			display: flex;
			gap: 0.45rem;
			flex-wrap: wrap;
			margin-top: 0.8rem;
		}
		.status-dot {
			width: 0.55rem;
			height: 0.55rem;
			border-radius: 50%;
			background: var(--success);
			box-shadow: 0 0 12px rgba(52, 211, 153, 0.75);
			margin-top: 0.28rem;
		}
		.subtle-divider {
			height: 1px;
			background: linear-gradient(90deg, transparent, rgba(148, 163, 184, 0.22), transparent);
			margin: 1rem 0;
		}
	</style>
	""",
	unsafe_allow_html=True,
)

st.markdown(
	"""
	<div class="hero">
		<div class="hero-grid">
			<div class="hero-copy">
				<div class="hero-kicker">Adaptive Storage Control</div>
				<h1>TempSched+ Dashboard</h1>
				<p>Command center for temperature-aware storage, cold-data compression, and encrypted archival movement across device, edge, cloud, and Firebase.</p>
				<div class="hero-badges">
					<span class="chip">Hot / Warm / Cold tiering</span>
					<span class="chip">Compression before archive</span>
					<span class="chip">Encrypted cold storage</span>
					<span class="chip">Real-time scheduling loop</span>
				</div>
			</div>
			<div class="signal-card">
				<div class="signal-title">Live System State</div>
				<div class="signal-value">TempSched+</div>
				<div class="signal-caption">A focused control surface for storage movement, archive visibility, and thermal awareness.</div>
				<div class="status-line"><span class="status-dot"></span><span class="small-note">Monitoring cold pipeline readiness</span></div>
			</div>
		</div>
	</div>
	""",
	unsafe_allow_html=True,
)

with st.sidebar:
	st.markdown(
		"""
		<div class='panel-card'>
			<div class='tier-title'>TempSched+ Control Deck</div>
			<div class='small-note'>Tech-focused dashboard for storage tiering, cold archive flow, and live thermal routing.</div>
		</div>
		""",
		unsafe_allow_html=True,
	)
	if st.button("Log out", use_container_width=True):
		st.session_state["authenticated"] = False
		st.rerun()
	st.markdown("<div class='subtle-divider'></div>", unsafe_allow_html=True)
	st.caption("Scan the device from the browser")
	st.file_uploader(
		"Upload files from this device",
		type=None,
		accept_multiple_files=True,
		help="Streamlit Cloud cannot read another machine's local disk directly. Upload files here to scan them from the visiting device.",
		key="device_uploads",
	)

	uploaded_files = st.session_state.get("device_uploads") or []
	if uploaded_files:
		st.info(f"{len(uploaded_files)} file(s) selected for this browser session.")

	quick_scan_max_files = int(getattr(config, "SCAN_QUICK_MAX_FILES", 100))

	col1, col2 = st.columns(2)
	with col1:
		if st.button(" Upload & Scan", use_container_width=True, disabled=not uploaded_files, help="Stage uploaded files and run a quick scan on them"):
			with st.status("Uploading and scanning...", expanded=True) as status:
				try:
					saved_paths = _save_uploaded_files(uploaded_files)
					st.cache_data.clear()
					st.write(f" Uploaded: {len(saved_paths)} file(s)")
					st.write(" Scanning uploaded device files...")
					cycle_result = cold_pipeline.process_files(scan_paths=[_upload_staging_dir()], max_files=quick_scan_max_files)
					st.session_state["scan_cycle"] = cycle_result
					st.session_state["uploaded_scan_paths"] = [str(path) for path in saved_paths]
					st.write(f" Scanned: {cycle_result['scanned']}")
					st.write(f" Hot: {cycle_result['hot']} | Warm: {cycle_result['warm']} | Cold: {cycle_result['cold']}")
					st.write(f" Staged: {cycle_result['staged']}")
					status.update(label="Upload scan complete!", state="complete")
				except Exception as e:
					st.error(f"Upload scan error: {e}")
					status.update(label="Upload scan failed", state="error")
			st.cache_data.clear()
			st.session_state["rerun"] = True

	with col2:
		if st.button(" Quick Scan", use_container_width=True, help="Scan the current uploaded device session"):
			with st.status("Scanning...", expanded=True) as status:
				try:
					st.write(" Finding files in the current device session...")
					cycle_result = cold_pipeline.process_files(scan_paths=[_upload_staging_dir()], max_files=quick_scan_max_files) if _uploaded_device_files() else cold_pipeline.process_files(max_files=quick_scan_max_files)
					st.session_state["scan_cycle"] = cycle_result
					st.write(f" Scanned: {cycle_result['scanned']}")
					st.write(f" Hot: {cycle_result['hot']} | Warm: {cycle_result['warm']} | Cold: {cycle_result['cold']}")
					st.write(f" Staged: {cycle_result['staged']}")
					status.update(label="Scan complete!", state="complete")
				except Exception as e:
					st.error(f"Scan error: {e}")
					status.update(label="Scan failed", state="error")
			st.cache_data.clear()
			st.session_state["rerun"] = True

	if st.button(" Full Scan", use_container_width=True, help="Complete scan for the current uploaded device session"):
		with st.status("Full scanning...", expanded=True) as status:
			try:
				st.write(" Finding files in the current device session...")
				cycle_result = cold_pipeline.process_files(scan_paths=[_upload_staging_dir()]) if _uploaded_device_files() else cold_pipeline.process_files()
				st.session_state["scan_cycle"] = cycle_result
				st.write(f" Scanned: {cycle_result['scanned']}")
				st.write(f" Hot: {cycle_result['hot']} | Warm: {cycle_result['warm']} | Cold: {cycle_result['cold']}")
				st.write(f" Staged: {cycle_result['staged']}")
				status.update(label="Full scan complete!", state="complete")
			except Exception as e:
				st.error(f"Full scan error: {e}")
				status.update(label="Scan failed", state="error")
			st.cache_data.clear()
			st.session_state["rerun"] = True

	if st.button("Run scheduling cycle", use_container_width=True):
		with st.status("Running scheduler...", expanded=False) as status:
			try:
				actions = scheduler.schedule()
				st.session_state["schedule_cycle"] = {
					"scheduled": len(actions),
					"hot": sum(1 for item in actions if item.get("tier") == "HOT"),
					"warm": sum(1 for item in actions if item.get("tier") == "WARM"),
					"cold": sum(1 for item in actions if item.get("tier") == "COLD"),
				}
				status.update(label="Scheduling complete!", state="complete")
			except Exception as e:
				st.error(f"Scheduler error: {e}")
				status.update(label="Scheduler failed", state="error")
		st.cache_data.clear()
		st.session_state["rerun"] = True

	if _uploaded_device_files():
		st.markdown("<div class='subtle-divider'></div>", unsafe_allow_html=True)
		st.markdown("<div class='small-note'>Current browser session uploads</div>", unsafe_allow_html=True)
		st.write(f"Uploaded files: {len(_uploaded_device_files())}")
		st.write(f"Uploaded bytes: {_count_bytes(_upload_staging_dir())} bytes")

	st.divider()
	st.markdown("<div class='small-note'>Storage tiers</div>", unsafe_allow_html=True)
	st.write(f"Device: {len(_list_files(config.DEVICE))}")
	st.write(f"Edge: {len(_list_files(config.EDGE))}")
	st.write(f"Cloud: {len(_list_files(config.CLOUD))}")

if st.session_state.pop("rerun", False):
	st.rerun()

# Fast data collection - cache expensive operations
@st.cache_data(ttl=30)
def _get_snapshot():
	return scheduler.snapshot()

@st.cache_data(ttl=60)
def _get_cloud_metadata():
	if cloud_backend.supabase_is_configured():
		try:
			return cloud_backend.list_metadata(limit=1000)
		except Exception:
			return []
	return []

@st.cache_data(ttl=45)
def _get_pipeline_stats():
	try:
		return cold_pipeline.get_pipeline_stats()
	except Exception:
		return {"compressed_records": 0, "saved_mb": 0}

# Collect data with defaults
snapshot = _get_snapshot()
cloud_records = snapshot.get("cloud_records", [])
temperature_store = snapshot.get("temperature_store", {})

if temperature_store:
    current_temperature = prediction.current_temperature(
        [
            item["temperature"]
            for item in temperature_store.values()
        ]
    )
else:
    current_temperature = 500.0

# Lazy load forecast for better performance
try:
    temp_values = [
        item["temperature"]
        for item in temperature_store.values()
    ] if temperature_store else []

    future_forecast = prediction.predict_system_future(
        temperature_store,
        horizon_hours=24
    )
except Exception:
	future_forecast = {
		"predicted_temperature": "n/a",
		"predicted_tier": "unknown",
		"confidence": "n/a",
	}
supabase_connected = cloud_backend.supabase_is_configured()
cloud_connected = supabase_connected or len(cloud_records) > 0 or len(snapshot.get("cloud", [])) > 0

# Load cloud metadata in background
cloud_records_remote = _get_cloud_metadata() if supabase_connected else []
pipeline_stats = _get_pipeline_stats()
last_scan_cycle = st.session_state.get("scan_cycle")
last_schedule_cycle = st.session_state.get("schedule_cycle")
scan_paths_count = len(getattr(config, "SCAN_PATHS", []))
scan_max_files = int(getattr(config, "SCAN_MAX_FILES", 1500))
if last_scan_cycle:
	last_activity_count = int(last_scan_cycle.get("scanned", 0))
	last_activity_caption = "Files inspected by cold pipeline scan"
elif last_schedule_cycle:
	last_activity_count = int(last_schedule_cycle.get("scheduled", 0))
	last_activity_caption = "Files processed by scheduling cycle"
else:
	last_activity_count = 0
	last_activity_caption = "Run Quick Scan or scheduling cycle"
cloud_record_count = len(cloud_records_remote)
cloud_upload_count = sum(1 for item in cloud_records_remote if str(item.get("tier", "")).lower() == "cold")

metric_cols = st.columns(6)
with metric_cols[0]:
	_render_metric("Device Files", len(snapshot.get("device", [])), f"{_count_bytes(config.DEVICE)} bytes")
with metric_cols[1]:
	_render_metric("Edge Files", len(snapshot.get("edge", [])), f"{_count_bytes(config.EDGE)} bytes")
with metric_cols[2]:
	_render_metric("Cloud Archives", len(snapshot.get("cloud", [])), f"{_count_bytes(config.CLOUD)} bytes")
with metric_cols[3]:
	_render_metric("Staged Records", pipeline_stats.get("compressed_records", 0), f"{len(snapshot.get('compressed', []))} local copies")
with metric_cols[4]:
	_render_metric("Processed (last run)", last_activity_count, last_activity_caption)
with metric_cols[5]:
	_render_metric("Current Temp", current_temperature, "Current state from recent temperature values")

forecast_cols = st.columns(3)
with forecast_cols[0]:
	_render_metric("Future Temp (24h)", future_forecast.get("predicted_temperature", "n/a"), "Transformer forecast for the next 24 hours")
with forecast_cols[1]:
	_render_metric("Future Tier", future_forecast.get("predicted_tier", "n/a"), "Predicted storage heat class")
with forecast_cols[2]:
	_render_metric("Forecast Confidence", future_forecast.get("confidence", "n/a"), "Model confidence score")

st.markdown("<div class='section-title'>AI Prediction Explorer</div>", unsafe_allow_html=True)

# Lazy load AI prediction section
with st.expander(" Individual File Prediction", expanded=False):
	candidate_files = []
	for path in _uploaded_device_files():
		if path.is_file():
			candidate_files.append(path)
	for filename in snapshot.get("device", []):
		path = config.DEVICE / filename
		if path.is_file():
			candidate_files.append(path)
	for filename in snapshot.get("edge", []):
		path = config.EDGE / filename
		if path.is_file():
			candidate_files.append(path)

	if candidate_files:
		select_options = [str(path) for path in sorted(candidate_files)]
		selected_file_text = st.selectbox("Select a file for 24h AI prediction", select_options, index=0)
		selected_file = Path(selected_file_text)
		try:
			file_stats = selected_file.stat()
			last_access_dt = datetime.fromtimestamp(float(file_stats.st_atime), tz=timezone.utc)

			file_features = {
				"path": str(selected_file),
				"size": int(file_stats.st_size),
				"last_access": float(file_stats.st_atime),
				"last_modified": float(file_stats.st_mtime),
				"session": "dashboard",
				"user": "local",
			}
			try:
				file_forecast = prediction.predict_future(file_features, horizon_hours=24)
			except Exception:
				file_forecast = {"predicted_tier": "unknown", "confidence": "n/a", "predicted_temperature": "n/a", "recommendation": "Unable to generate prediction."}
			
			access_30d = _access_stats_30d(selected_file)

			explorer_cols = st.columns(3)
			with explorer_cols[0]:
				_render_metric("Predicted Tier (24h)", file_forecast.get("predicted_tier", "n/a"), "HOT/WARM/COLD classification")
			with explorer_cols[1]:
				_render_metric("Confidence", file_forecast.get("confidence", "n/a"), "Probability-style confidence score")
			with explorer_cols[2]:
				_render_metric("Predicted Temp", file_forecast.get("predicted_temperature", "n/a"), "24-hour future thermal score")

			st.markdown(
				f"""
				<div class='panel-card'>
					<div class='tier-title'>Migration Recommendation</div>
					<div class='small-note'>{file_forecast.get('recommendation', 'No recommendation available.')}</div>
				</div>
				""",
				unsafe_allow_html=True,
			)

			feature_data = [
				{"Feature": "Past 30-day access count", "Value": str(access_30d["past_30d_accesses"])},
				{"Feature": "Average accesses/day (30d)", "Value": str(access_30d["avg_daily_accesses"])},
				{"Feature": "Last accessed (UTC)", "Value": str(last_access_dt.isoformat())},
				{"Feature": "File type", "Value": str(selected_file.suffix.lower() or "<none>")},
				{"Feature": "File size (bytes)", "Value": str(int(file_stats.st_size))},
				{"Feature": "Hour feature", "Value": str(int(last_access_dt.hour))},
				{"Feature": "Day-of-week feature", "Value": str(int(last_access_dt.weekday()))},
			]
			st.dataframe(
				feature_data,
				use_container_width=True,
				hide_index=True,
			)
		except Exception as e:
			st.error(f"Error analyzing file: {e}")
	else:
		st.info("No files are staged in device/edge tiers yet. Run a scan and scheduling cycle to enable file-level AI prediction.")

st.markdown("<div class='section-title'>Operational Signals</div>", unsafe_allow_html=True)
signal_cols = st.columns(4)
with signal_cols[0]:
	_render_metric("Adaptive Scan Paths", scan_paths_count, "Documents and Downloads by default")
with signal_cols[1]:
	_render_metric("Temperature History", len(temperature_store), "Tracked file hotness samples")
with signal_cols[2]:
	_render_metric("Cloud Records", len(cloud_records), "Indexed archives visible in cloud")
with signal_cols[3]:
	_render_metric("Supabase Sync", "On" if supabase_connected else "Off", "Bucket and metadata status")

storage_cols = st.columns(3)
with storage_cols[0]:
	_render_metric("Staged Data", f"{pipeline_stats['saved_mb']} MB", "Bytes copied into the device tier")
with storage_cols[1]:
	_render_metric("Scan Paths", scan_paths_count, "Documents/Downloads by default")
with storage_cols[2]:
	_render_metric("Max Scan Files", scan_max_files, "Per scan cycle")

cloud_cols = st.columns(3)
with cloud_cols[0]:
	_render_metric("Cloud Objects", cloud_record_count, "Objects listed from Supabase Storage")
with cloud_cols[1]:
	_render_metric("Cloud Uploads", cloud_upload_count, "Cold files sent to the bucket")
with cloud_cols[2]:
	_render_metric("Supabase Ready", "Yes" if supabase_connected else "No", "URL, publishable key, and bucket detected")

st.markdown(
	"""
	<div class='panel-card'>
		<div class='tier-title'>Connectivity Matrix</div>
		<div class='small-note'>Supabase Storage is used when the URL, publishable key, and bucket are configured. The local cloud folder remains available as a fallback archive and registry.</div>
	</div>
	""",
	unsafe_allow_html=True,
)

st.write(f"Supabase connected: {'Yes' if supabase_connected else 'Not yet'}")
st.write(f"Cloud connected: {'Yes' if cloud_connected else 'Not yet'}")

if supabase_connected:
	st.success("Supabase is configured and ready for uploads and object listing.")
else:
	st.warning("Supabase is not configured yet, so the dashboard is showing local cloud storage state only.")

if last_scan_cycle:
	st.success(
		f"Last scan: scanned {last_scan_cycle.get('scanned', 0)} files, hot={last_scan_cycle.get('hot', 0)}, warm={last_scan_cycle.get('warm', 0)}, cold={last_scan_cycle.get('cold', 0)}, staged={last_scan_cycle.get('staged', 0)}"
	)
elif last_schedule_cycle:
	st.success(
		f"Last schedule: processed {last_schedule_cycle.get('scheduled', 0)} files, hot={last_schedule_cycle.get('hot', 0)}, warm={last_schedule_cycle.get('warm', 0)}, cold={last_schedule_cycle.get('cold', 0)}"
	)

st.markdown("<div class='section-title'>Thermal Status</div>", unsafe_allow_html=True)

# Show tier statistics from last scan if available, otherwise show current snapshot counts
if last_scan_cycle:
	hot_count = int(last_scan_cycle.get("hot", 0))
	warm_count = int(last_scan_cycle.get("warm", 0))
	cold_count = int(last_scan_cycle.get("cold", 0))
else:
	# Fallback: show current tier file counts from snapshot
	hot_count = len(snapshot.get("device", []))
	warm_count = len(snapshot.get("edge", []))
	cold_count = len(snapshot.get("cloud", []))

hot_files = last_scan_cycle.get("hot_files", []) if last_scan_cycle else []

hot_cols = st.columns(3)
with hot_cols[0]:
	_render_metric("Hot (device tier)", hot_count, "Frequently accessed files")
with hot_cols[1]:
	_render_metric("Warm (edge tier)", warm_count, "Moderate access files")
with hot_cols[2]:
	_render_metric("Cold (cloud tier)", cold_count, "Rarely accessed files")

if hot_files:
	st.write("Hot files detected in last scan:")
	st.dataframe(
		[{"Hot File Path": path} for path in hot_files],
		use_container_width=True,
		hide_index=True,
	)

# Use expander for detailed classification data
if last_scan_cycle:
	with st.expander(" Detailed Classification Data", expanded=False):
		classified_rows = last_scan_cycle.get("classified", [])
		if classified_rows:
			st.write("Classification results:")
			st.dataframe(
				[
					{
						"Path": item.get("path", ""),
						"Decision": str(item.get("decision", "")).upper(),
						"Rule Decision": str(item.get("rule_decision", "")).upper(),
						"AI Decision": str(item.get("ai_decision", "")).upper(),
						"Current Temp Score": item.get("predicted_temperature", ""),
						"Size (KB)": round(float(item.get("size", 0)) / 1024, 2),
					}
					for item in classified_rows
				],
				use_container_width=True,
				hide_index=True,
			)
		else:
			st.info("No classification rows were produced for the last scan cycle.")

		entries_rows = last_scan_cycle.get("entries", [])
		if entries_rows:
			st.write("Staged entries:")
			st.dataframe(
				[
					{
						"Path": item.get("original_path", ""),
						"Decision": str(item.get("decision", "")).upper(),
						"Rule Decision": str(item.get("rule_decision", "")).upper(),
						"AI Decision": str(item.get("ai_decision", "")).upper(),
						"Temperature": item.get("predicted_temperature", ""),
						"Staged Path": item.get("staged_path", ""),
						"Tier": item.get("staged_tier", ""),
					}
					for item in entries_rows
				],
				use_container_width=True,
				hide_index=True,
			)

		with st.expander("Raw scan payload", expanded=False):
			st.json(last_scan_cycle)

st.markdown("<div class='section-title'>Tier Overview</div>", unsafe_allow_html=True)
tier_cols = st.columns(3)
with tier_cols[0]:
	st.markdown("<div class='panel-card'><div class='tier-title'>Device Tier</div>", unsafe_allow_html=True)
	st.write(f"Files: {len(snapshot.get('device', []))}")
	st.write(f"Size: {_count_bytes(config.DEVICE)} bytes")
	st.markdown("</div>", unsafe_allow_html=True)
with tier_cols[1]:
	st.markdown("<div class='panel-card'><div class='tier-title'>Edge Tier</div>", unsafe_allow_html=True)
	st.write(f"Files: {len(snapshot.get('edge', []))}")
	st.write(f"Size: {_count_bytes(config.EDGE)} bytes")
	st.markdown("</div>", unsafe_allow_html=True)
with tier_cols[2]:
	st.markdown("<div class='panel-card'><div class='tier-title'>Cloud Tier</div>", unsafe_allow_html=True)
	st.write(f"Files: {len(snapshot.get('cloud', []))}")
	st.write(f"Size: {_count_bytes(config.CLOUD)} bytes")
	st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='section-title'>Cold Data Pipeline</div>", unsafe_allow_html=True)
pipeline_cols = st.columns([1.15, 0.85])
with pipeline_cols[0]:
    st.markdown(
        """
        <div class='panel-card'>
            <div class='tier-title'>Cold Archive Flow</div>
            <div class='small-note'>Files are scanned into the device tier first. The scheduler then moves hot files to device, warm files to edge, and cold files to cloud after compression and encryption. Cold archives are also uploaded to Firebase Storage.</div>
            <ol>
                <li>Scanned file is staged into the device tier.</li>
                <li>Scheduler dynamically calculates Hot/Warm boundaries.</li>
                <li>Warm files move to edge storage.</li>
                <li>Cold files are compressed, encrypted, and archived to cloud.</li>
            </ol>
        </div>
        """,
        unsafe_allow_html=True,
    )
with pipeline_cols[1]:
    st.markdown("<div class='panel-card'><div class='tier-title'>Temperature Snapshot</div>", unsafe_allow_html=True)
    if temperature_store:
        # Fetch the real-time adaptive thresholds to properly categorize the dashboard display
        adaptive_hot, adaptive_warm = scheduler._get_adaptive_thresholds(temperature_store)
        
        temp_counts = Counter(
            scheduler.classify_temperature(
                item["temperature"], adaptive_hot, adaptive_warm
            )
            for item in temperature_store.values()
        )
        st.write({tier: temp_counts.get(tier, 0) for tier in ["HOT", "WARM", "COLD"]})
        
        st.markdown("<div class='small-note'><strong>Live Adaptive Thresholds:</strong></div>", unsafe_allow_html=True)
        st.write(f"Hot Boundary: {round(adaptive_hot, 2)}")
        st.write(f"Warm Boundary: {round(adaptive_warm, 2)}")
    else:
        st.write("No temperature history yet. Run a scheduling cycle to populate this panel.")
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='section-title'>Current Temperature</div>", unsafe_allow_html=True)
st.markdown(
	f"""
	<div class='panel-card'>
		<div class='tier-title'>Current System Temperature</div>
		<div class='metric-value'>{current_temperature}</div>
		<div class='small-note'>This is the current temperature estimate from the latest scheduler state.</div>
	</div>
	""",
	unsafe_allow_html=True,
)

st.markdown(
	f"""
	<div class='panel-card'>
		<div class='tier-title'>AI Migration Recommendation</div>
		<div class='small-note'>Future temp (24h): {future_forecast.get('predicted_temperature', 'n/a')} | Tier: {future_forecast.get('predicted_tier', 'n/a')} | Confidence: {future_forecast.get('confidence', 'n/a')}</div>
		<div class='subtle-divider'></div>
		<div class='small-note'>{future_forecast.get('recommendation', 'No recommendation available yet.')}</div>
	</div>
	""",
	unsafe_allow_html=True,
)

st.markdown("<div class='section-title'>Archive Registry</div>", unsafe_allow_html=True)
with st.expander(" Cloud Archive Records", expanded=False):
	if cloud_records:
		st.dataframe(
			[
				{
					"File": item["filename"],
					"Cloud Object": item["cloud_object"],
					"Firebase Object": item.get("firebase_object", ""),
					"Temperature": item["temperature"],
					"Size (bytes)": item["size_bytes"],
					"Compressed Path": item.get("compressed_path", ""),
					"Encrypted Path": item.get("encrypted_path", ""),
					"Checksum": item.get("checksum", ""),
					"Stored At": item["stored_at"],
				}
				for item in cloud_records
			],
			use_container_width=True,
			hide_index=True,
		)
	else:
		st.info("Archive registry is empty. Cold files will appear here after the first scheduling cycle.")

st.markdown("<div class='section-title'>Recent Cold Compression Records</div>", unsafe_allow_html=True)
with st.expander(" Compression & Encryption History", expanded=False):
	if cloud_records:
		compressed_rows = [
			{
				"Original Path": item.get("filename", ""),
				"Temperature": item.get("temperature", ""),
				"Compressed Path": item.get("compressed_path", ""),
				"Encrypted Path": item.get("encrypted_path", ""),
				"Cloud Object": item.get("cloud_object", ""),
				"Firebase Object": item.get("firebase_object", ""),
				"Checksum": item.get("checksum", ""),
				"Size (bytes)": item.get("size_bytes", ""),
				"Stored At": item.get("stored_at", ""),
			}
			for item in reversed(cloud_records)
			if item.get("compressed_path")
		]
		if compressed_rows:
			st.dataframe(
				compressed_rows,
				use_container_width=True,
				hide_index=True,
			)
		else:
			st.info("No compressed cold files are available yet.")
	else:
		st.info("No cold archive records are available yet.")
