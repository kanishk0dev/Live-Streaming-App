# Live Streaming Platform
 
A real-time live streaming application built using HTML, CSS, JavaScript, Python (Flask), WebRTC, and Socket.IO.
 
This application allows users to:
- Register and login with email and password
- Complete profile with full name, profile picture, and short intro video
- Go live and broadcast in real-time
- Watch live streams of other users
- Track live viewer count
- Access the platform as a guest to watch streams
---
 
# Features
 
- User registration and login
- Profile completion with photo and video upload
- Real-time live streaming using WebRTC
- Live viewer count tracking
- Guest access to watch live streams
- Go Live restricted to users with completed profiles
- Stream ended notification for viewers
- Camera flip and mute controls
- Live duration timer
- Mobile-inspired UI
- Responsive layout for both mobile and desktop
---
 
# Technologies Used
 
## Frontend
- HTML5
- CSS3
- JavaScript
## Backend
- Python
- Flask
- Flask-SocketIO
## Real-time Communication
- WebRTC
- Socket.IO
## Database
- SQLite
## Deployment
- Render
- Gunicorn
- Gevent WebSocket Worker
---
 
# Project Structure
 
```bash
livestream-app/
│
├── static/
│   ├── index.css
│   ├── login.css
│   ├── signup.css
│   ├── profile.css
│   ├── landing.css
│   ├── go-live.css
│   └── watch.css
│
├── templates/
│   ├── index.html
│   ├── login.html
│   ├── signup.html
│   ├── profile.html
│   ├── landing.html
│   ├── go-live.html
│   └── watch.html
│
├── app.py
├── requirements.txt
├── Procfile
└── README.md
```
