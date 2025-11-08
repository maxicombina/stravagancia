# What's this about
A project to learn Python+Django by creating a small web app to track my Strava Ride activities.

# Why
On one hand, I am learning Python+Django.

On the other hand, I want to keep track of my personal Strava Ride activities and be able to visualize data in ways which are not always present in Strava no Garmin Connect.

So, why not?
It's a good excuse to learn something new and useful, while being able to view my Ride data in the way I want.

# What does it do?
- Loads one Strava athlete
- Stores all the Ride activities
- Detect missing activities, and ability to load only those
- Leverages the Djando admin interface to manage models
- Using docker (with the provided `docker-compose.yml`, a Metabase instance can be launched to visualize the data

# Known issues and limitations
- Only one user supported
- Docker not used for Django, only for Metabase
- Uses the default `db.sqlite3`. No need for a real DB, but may not be your case.

# Next steps
- Improve some basic visualizations of the data (e.g., total distance per month, average speed, calories per month)
- Have a simple web interface to view and potentially manipulate some of the data
- Get this project to live in the Cloud
- Resources:
  - https://medium.com/@codingforinnovations/deploying-a-django-app-to-production-with-vercel-in-less-than-8-minutes-0877a21af4f3
  - https://neon.com/ database

# How to use this project
 * Enable the Strava API. As of this writing, go to https://www.strava.com/settings/api and create an app.
 * Populate the `.env` file. See `.env.example` to learn the environment variables needed
 * ...
