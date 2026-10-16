# Architecture

```
Browser (React/Vite) --Bearer JWT--> FastAPI --+--> ML pipeline (joblib, scikit-learn)
        |                                       +--> Repository: Supabase PostgREST (RLS)  | SQLite (local/tests)
        +--> Supabase Auth (sign-in, sessions)
```
- Frontend never talks to the database; it calls FastAPI with the Supabase access token.
- FastAPI derives the user id and role from the verified token, never from the request body.
- The model artifact stores the sklearn Pipeline (preprocessing + Random Forest), feature schema hash, version and metrics. Loading refuses a schema mismatch.
- Risk level and prediction are computed server-side from the model probability only.
