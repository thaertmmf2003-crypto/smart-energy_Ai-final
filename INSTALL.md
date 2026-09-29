# Smart Energy AI — Multi-Page Premium UI

This package replaces the single-page dashboard presentation with separate Flask pages while keeping the existing backend APIs.

## 1. Copy the files

Copy:

- `page_routes.py` → project root
- `templates/*` → your `templates/` folder
- `static/css/app.css` → `static/css/`
- `static/js/app.js` → `static/js/`

Keep your existing:

- `static/vendor/chart.umd.min.js`
- backend files
- `/api/...` endpoints

## 2. Register the page blueprint in `app.py`

Near your Flask imports:

```python
from page_routes import pages
```

After:

```python
app = Flask(__name__)
```

add:

```python
app.register_blueprint(pages)
```

## 3. Change the existing `/` route

Your current root route probably returns the old `dashboard.html`.

Change only the return line so it renders:

```python
return render_template("overview.html", page="overview", title="Overview")
```

Do not create a second `/` route.

## 4. Important

The new frontend expects these existing APIs:

- `/api/health`
- `/api/dashboard`
- `/api/energy`
- `/api/events`
- `/api/agent/status`
- `/api/agent/run`
- `/api/agent/approve`
- `/api/agent/reject`
- `/api/agent/reset`
- `/api/agent/history`
- `/api/verification`
- `/api/rag/query`

Your backend architecture does not need to be rewritten.

## 5. Pages

- `/overview`
- `/energy`
- `/operations`
- `/digital-twin`
- `/verification`
- `/knowledge`
- `/activity`

The sidebar opens each page independently.

## 6. Palette

Main visual language:

- Gold: `#DEB85C`
- Dark burgundy: `#5C1121`
- Gold highlight: `#F1D58A`
- Near-black background: `#080709`

The gold is intentionally used as an accent rather than covering the whole interface, while burgundy is used for navigation, hero surfaces and AI-state emphasis.

## 7. Run

From the project root:

```powershell
python app.py
```

Then open:

```text
http://127.0.0.1:5000/
```
