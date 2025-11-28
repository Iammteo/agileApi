
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
# docs.py

# Swagger / Flasgger docs for all endpoints

health_check_docs = """
Health check
A simple endpoint to verify the API is running.
---
tags:
  - System
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

list_observations_docs = """
List observations
Returns all observations, optionally filtered by date range and region.
---
tags:
  - Observations
parameters:
  - name: start_date
    in: query
    type: string
    required: false
    description: |
      Start of date range (ISO 8601, e.g. 2025-01-01 or 2025-01-01T00:00:00).
  - name: end_date
    in: query
    type: string
    required: false
    description: |
      End of date range (ISO 8601, e.g. 2025-01-31 or 2025-01-31T23:59:59).
  - name: region
    in: query
    type: string
    required: false
    description: Region / location identifier matching data.region.
responses:
  200:
    description: Filtered list of observations
    schema:
      type: array
      items:
        type: object
        properties:
          id:
            type: integer
            example: 1
          data:
            type: object
            example:
              timestamp: "2025-01-10T12:00:00Z"
              region: "EU"
              value: 1
  400:
    description: Invalid query parameter (e.g. bad date format)
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: BAD_REQUEST
            message:
              type: string
"""

create_observation_docs = """
Create an observation
Creates a new observation record.
---
tags:
  - Observations
consumes:
  - application/json
parameters:
  - name: body
    in: body
    required: true
    schema:
      type: object
      description: Arbitrary observation payload stored under data.
      example:
        timestamp: "2025-01-10T12:00:00Z"
        region: "EU"
        value: 1
responses:
  201:
    description: Observation created
    schema:
      type: object
      properties:
        id:
          type: integer
          example: 1
        data:
          type: object
          example:
            timestamp: "2025-01-10T12:00:00Z"
            region: "EU"
            value: 1
  415:
    description: Request body was not JSON
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: UNSUPPORTED_MEDIA_TYPE
            message:
              type: string
"""

get_observation_docs = """
Get an observation
Returns a single observation by ID.
---
tags:
  - Observations
parameters:
  - name: obs_id
    in: path
    type: integer
    required: true
    description: Observation ID.
responses:
  200:
    description: Observation found
    schema:
      type: object
      properties:
        id:
          type: integer
          example: 1
        data:
          type: object
          example:
            timestamp: "2025-01-10T12:00:00Z"
            region: "EU"
            value: 1
  404:
    description: Observation not found
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: NOT_FOUND
            message:
              type: string
"""

replace_observation_docs = """
Replace an observation
Fully replaces an observation's data by ID (PUT).
---
tags:
  - Observations
consumes:
  - application/json
parameters:
  - name: obs_id
    in: path
    type: integer
    required: true
    description: Observation ID.
  - name: body
    in: body
    required: true
    schema:
      type: object
      description: New observation payload (will overwrite existing data).
      example:
        timestamp: "2025-02-01T09:00:00Z"
        region: "US"
        value: 99
responses:
  200:
    description: Observation updated
    schema:
      type: object
      properties:
        id:
          type: integer
        data:
          type: object
  404:
    description: Observation not found
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: NOT_FOUND
            message:
              type: string
  415:
    description: Request body was not JSON
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: UNSUPPORTED_MEDIA_TYPE
            message:
              type: string
"""

patch_observation_docs = """
Patch an observation
Partially updates an observation's data by ID (PATCH).
---
tags:
  - Observations
consumes:
  - application/json
parameters:
  - name: obs_id
    in: path
    type: integer
    required: true
    description: Observation ID.
  - name: body
    in: body
    required: true
    schema:
      type: object
      description: Partial payload to merge into data.
      example:
        value: 42
responses:
  200:
    description: Observation updated
    schema:
      type: object
      properties:
        id:
          type: integer
        data:
          type: object
  404:
    description: Observation not found
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: NOT_FOUND
            message:
              type: string
  415:
    description: Request body was not JSON
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: UNSUPPORTED_MEDIA_TYPE
            message:
              type: string
"""

delete_observation_docs = """
Delete an observation
Deletes an observation by ID.
---
tags:
  - Observations
parameters:
  - name: obs_id
    in: path
    type: integer
    required: true
    description: Observation ID.
responses:
  204:
    description: Observation deleted
  404:
    description: Observation not found
    schema:
      type: object
      properties:
        error:
          type: object
          properties:
            code:
              type: string
              example: NOT_FOUND
            message:
              type: string
"""