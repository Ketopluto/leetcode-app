from app import app

# This is the WSGI entry point for Vercel
# def handler(request, context):
#     return app(request.environ, context)

# # For local testing
if __name__ == "__main__":
    app.run(debug=True, port=5000)
