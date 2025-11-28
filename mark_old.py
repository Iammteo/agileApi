from datetime import datetime
from app import app, db, Observation

# Choose which record you want to make "old"
TARGET_ID = 1  # change this if you want another id

with app.app_context():
    obs = Observation.query.get(TARGET_ID)
    if not obs:
        print(f"No observation found with id={TARGET_ID}")
    else:
        # Set created_at to a date in a previous quarter
        # (e.g. 15 January 2024 – definitely before current quarter)
        obs.created_at = datetime(2024, 1, 15, 12, 0, 0)

        db.session.commit()
        print(f"Updated created_at for id={TARGET_ID} to {obs.created_at}")
