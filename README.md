# School Voting

A Flask web app for running school prefect elections. Students can sign in with
their school Google account and admins can manage the election.

**Week 1:** Google sign-in, role-based dashboards (admin / voter),
CSRF protection, custom error pages.

## To Run it Locally

```bash
git clone https://github.com/Astral-Viscount/School-Voting.git
cd School-Voting
python -m venv venv
\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python utils/secret_token.py
python utils/create_db.py
```

# Google OAuth
You need a Google OAuth Client ID 
For the Authorised JavaScript origins: `http://localhost:5000`
        Authorised redirect URIs     : `http://localhost:5000/login`

# Create your .env file

```
SECRET_KEY=paste-the-generated-secret-token
GOOGLE_CLIENT_ID=paste-the-client-id
ADMIN_EMAILS=your_email@gmail.com
SCHOOL_DOMAIN=@gmail.com
```

And now you can run the app and visit `http://localhost:5000` to use the website.