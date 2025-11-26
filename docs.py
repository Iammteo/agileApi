
health_check_docs = """
Health Check
---
tags:
  - Health
summary: Check if the API is running
description: Returns a simple JSON object to indicate that the API is healthy.
responses:
  200:
    description: API is healthy
    schema:
      type: object
      properties:
        status:
          type: string
          example: ok
"""
