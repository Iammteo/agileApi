import pytest
import os
import jwt
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from app import app, db, Observation

load_dotenv()

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def client():
    """Create test client"""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()


@pytest.fixture
def jwt_secret():
    """Get the JWT secret from environment or use the app's configured secret"""
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        with app.app_context():
            secret = app.config.get("JWT_SECRET_KEY", "your-secret-key-here")
    return secret


@pytest.fixture
def valid_token(jwt_secret):
    """Generate a valid JWT token for testing"""
    # Use environment variable if available
    token = os.getenv("DJANGO_TEST_TOKEN")
    if token:
        return token
    
    # Generate fresh token
    payload = {
        "user_id": 1,
        "sub": "test@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


@pytest.fixture
def expired_token(jwt_secret):
    """Generate an expired JWT token for testing"""
    payload = {
        "user_id": 1,
        "sub": "test@example.com",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "iat": datetime.now(timezone.utc) - timedelta(hours=2)
    }
    return jwt.encode(payload, jwt_secret, algorithm="HS256")


@pytest.fixture
def auth_headers(valid_token):
    """Headers with valid authentication"""
    return {
        "Authorization": f"Bearer {valid_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
def sample_observation_data():
    """Sample observation data for testing"""
    return {
        "timestamp": "2025-12-07T12:00:00Z",
        "timezone": "UTC",
        "latitude": 51.5074,
        "longitude": -0.1278,
        "satellite_id": "SAT-TEST-001",
        "notes": "Test observation"
    }


@pytest.fixture
def historical_observation_data():
    """Historical observation (before current quarter) for testing"""
    return {
        "timestamp": "2024-01-01T12:00:00Z",
        "timezone": "UTC",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "satellite_id": "SAT-HISTORICAL",
        "notes": "Historical record"
    }


# ============================================================================
# Health Check Tests
# ============================================================================

class TestHealthCheck:
    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json["status"] == "ok"


# ============================================================================
# Authentication Tests
# ============================================================================

class TestAuthentication:
    def test_missing_auth_header(self, client):
        """Test request without authentication header"""
        response = client.get("/api/observations")
        assert response.status_code == 401
        assert "UNAUTHENTICATED" in response.json["error"]

    def test_invalid_auth_format(self, client):
        """Test request with invalid auth format"""
        headers = {"Authorization": "InvalidFormat token123"}
        response = client.get("/api/observations", headers=headers)
        assert response.status_code == 401

    def test_invalid_token(self, client):
        """Test request with invalid token"""
        headers = {
            "Authorization": "Bearer invalid.token.here",
            "Content-Type": "application/json"
        }
        response = client.get("/api/observations", headers=headers)
        assert response.status_code == 401

    def test_expired_token(self, client, expired_token):
        """Test request with expired token"""
        headers = {
            "Authorization": f"Bearer {expired_token}",
            "Content-Type": "application/json"
        }
        response = client.get("/api/observations", headers=headers)
        assert response.status_code == 401
        assert "expired" in response.json["message"].lower()


# ============================================================================
# Observation CRUD Tests
# ============================================================================

class TestObservationCreate:
    def test_create_observation_success(self, client, auth_headers, sample_observation_data):
        """Test successful observation creation"""
        response = client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        assert response.status_code == 201
        assert response.json["satellite_id"] == "SAT-TEST-001"
        assert response.json["latitude"] == 51.5074
        assert "id" in response.json

    def test_create_observation_missing_required_fields(self, client, auth_headers):
        """Test creation with missing required fields"""
        incomplete_data = {
            "timestamp": "2025-12-07T12:00:00Z",
            "latitude": 51.5074
            # Missing: timezone, longitude, satellite_id
        }
        response = client.post("/api/observations", headers=auth_headers, json=incomplete_data)
        assert response.status_code == 400
        assert "VALIDATION_ERROR" in response.json["error"]

    def test_create_observation_invalid_timestamp(self, client, auth_headers):
        """Test creation with invalid timestamp format"""
        data = {
            "timestamp": "invalid-date",
            "timezone": "UTC",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "satellite_id": "SAT-TEST-001"
        }
        response = client.post("/api/observations", headers=auth_headers, json=data)
        assert response.status_code == 400

    def test_create_observation_invalid_coordinates(self, client, auth_headers):
        """Test creation with invalid coordinates"""
        data = {
            "timestamp": "2025-12-07T12:00:00Z",
            "timezone": "UTC",
            "latitude": "not-a-number",
            "longitude": -0.1278,
            "satellite_id": "SAT-TEST-001"
        }
        response = client.post("/api/observations", headers=auth_headers, json=data)
        assert response.status_code == 400

    def test_create_observation_with_spectral_indices(self, client, auth_headers):
        """Test creation with spectral indices"""
        data = {
            "timestamp": "2025-12-07T12:00:00Z",
            "timezone": "UTC",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "satellite_id": "SAT-TEST-001",
            "spectral_indices": {
                "NDVI": 0.75,
                "EVI": 0.65
            },
            "notes": "With spectral data"
        }
        response = client.post("/api/observations", headers=auth_headers, json=data)
        assert response.status_code == 201
        assert response.json["spectral_indices"]["NDVI"] == 0.75

    def test_create_observation_non_json_payload(self, client, auth_headers):
        """Test creation with non-JSON payload"""
        response = client.post(
            "/api/observations",
            headers={"Authorization": auth_headers["Authorization"]},
            data="not json"
        )
        assert response.status_code == 400


class TestObservationRead:
    def test_get_all_observations_empty(self, client, auth_headers):
        """Test getting observations when database is empty"""
        response = client.get("/api/observations", headers=auth_headers)
        assert response.status_code == 200
        assert response.json == []

    def test_get_all_observations(self, client, auth_headers, sample_observation_data):
        """Test getting all observations"""
        # Create some observations
        client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        
        data2 = sample_observation_data.copy()
        data2["satellite_id"] = "SAT-TEST-002"
        client.post("/api/observations", headers=auth_headers, json=data2)
        
        # Get all
        response = client.get("/api/observations", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json) == 2

    def test_get_observation_by_id(self, client, auth_headers, sample_observation_data):
        """Test getting a specific observation by ID"""
        # Create observation
        create_response = client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        obs_id = create_response.json["id"]
        
        # Get by ID
        response = client.get(f"/api/observations/{obs_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json["id"] == obs_id
        assert response.json["satellite_id"] == "SAT-TEST-001"

    def test_get_nonexistent_observation(self, client, auth_headers):
        """Test getting observation that doesn't exist"""
        response = client.get("/api/observations/99999", headers=auth_headers)
        assert response.status_code == 404
        assert "NOT_FOUND" in response.json["error"]

    def test_filter_by_timestamp(self, client, auth_headers):
        """Test filtering observations by timestamp"""
        # Create observations at different times
        data1 = {
            "timestamp": "2025-12-01T12:00:00Z",
            "timezone": "UTC",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "satellite_id": "SAT-DEC-01"
        }
        data2 = {
            "timestamp": "2025-12-10T12:00:00Z",
            "timezone": "UTC",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "satellite_id": "SAT-DEC-10"
        }
        client.post("/api/observations", headers=auth_headers, json=data1)
        client.post("/api/observations", headers=auth_headers, json=data2)
        
        # Filter
        response = client.get(
            "/api/observations?start_timestamp=2025-12-05T00:00:00Z",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert len(response.json) == 1
        assert response.json[0]["satellite_id"] == "SAT-DEC-10"

    def test_filter_by_coordinates(self, client, auth_headers):
        """Test filtering observations by coordinates"""
        # Create observations at different locations
        data1 = {
            "timestamp": "2025-12-07T12:00:00Z",
            "timezone": "UTC",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "satellite_id": "SAT-LONDON"
        }
        data2 = {
            "timestamp": "2025-12-07T12:00:00Z",
            "timezone": "UTC",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "satellite_id": "SAT-NYC"
        }
        client.post("/api/observations", headers=auth_headers, json=data1)
        client.post("/api/observations", headers=auth_headers, json=data2)
        
        # Filter by latitude
        response = client.get(
            "/api/observations?min_lat=50&max_lat=52",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert len(response.json) == 1
        assert response.json[0]["satellite_id"] == "SAT-LONDON"


class TestObservationUpdate:
    def test_update_observation_put(self, client, auth_headers, sample_observation_data):
        """Test full update (PUT) of observation"""
        # Create observation
        create_response = client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        obs_id = create_response.json["id"]
        
        # Update
        updated_data = {
            "timestamp": "2025-12-08T15:00:00Z",
            "timezone": "EST",
            "latitude": 40.7128,
            "longitude": -74.0060,
            "satellite_id": "SAT-UPDATED",
            "notes": "Updated observation"
        }
        response = client.put(f"/api/observations/{obs_id}", headers=auth_headers, json=updated_data)
        assert response.status_code == 200
        assert response.json["satellite_id"] == "SAT-UPDATED"
        assert response.json["latitude"] == 40.7128

    def test_update_observation_patch(self, client, auth_headers, sample_observation_data):
        """Test partial update (PATCH) of observation"""
        # Create observation
        create_response = client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        obs_id = create_response.json["id"]
        
        # Partial update
        patch_data = {
            "notes": "Partially updated",
            "satellite_id": "SAT-PATCHED"
        }
        response = client.patch(f"/api/observations/{obs_id}", headers=auth_headers, json=patch_data)
        assert response.status_code == 200
        assert response.json["satellite_id"] == "SAT-PATCHED"
        assert response.json["notes"] == "Partially updated"
        # Original fields should remain
        assert response.json["latitude"] == 51.5074

    def test_update_nonexistent_observation(self, client, auth_headers, sample_observation_data):
        """Test updating observation that doesn't exist"""
        response = client.put("/api/observations/99999", headers=auth_headers, json=sample_observation_data)
        assert response.status_code == 404

    def test_update_historical_observation_forbidden(self, client, auth_headers, historical_observation_data):
        """Test that historical observations cannot be updated"""
        # Create historical observation
        create_response = client.post("/api/observations", headers=auth_headers, json=historical_observation_data)
        obs_id = create_response.json["id"]
        
        # Try to update
        update_data = {"notes": "Trying to update historical"}
        response = client.patch(f"/api/observations/{obs_id}", headers=auth_headers, json=update_data)
        assert response.status_code == 403
        assert "FORBIDDEN" in response.json["error"]


class TestObservationDelete:
    def test_delete_observation(self, client, auth_headers, sample_observation_data):
        """Test deleting an observation"""
        # Create observation
        create_response = client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        obs_id = create_response.json["id"]
        
        # Delete
        response = client.delete(f"/api/observations/{obs_id}", headers=auth_headers)
        assert response.status_code == 200
        assert "deleted" in response.json["message"].lower()
        
        # Verify it's gone
        get_response = client.get(f"/api/observations/{obs_id}", headers=auth_headers)
        assert get_response.status_code == 404

    def test_delete_nonexistent_observation(self, client, auth_headers):
        """Test deleting observation that doesn't exist"""
        response = client.delete("/api/observations/99999", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_historical_observation_forbidden(self, client, auth_headers, historical_observation_data):
        """Test that historical observations cannot be deleted"""
        # Create historical observation
        create_response = client.post("/api/observations", headers=auth_headers, json=historical_observation_data)
        obs_id = create_response.json["id"]
        
        # Try to delete
        response = client.delete(f"/api/observations/{obs_id}", headers=auth_headers)
        assert response.status_code == 403
        assert "FORBIDDEN" in response.json["error"]


# ============================================================================
# Bulk Operations Tests
# ============================================================================

class TestBulkOperations:
    def test_bulk_create_success(self, client, auth_headers):
        """Test bulk creation of observations"""
        bulk_data = [
            {
                "timestamp": "2025-12-07T12:00:00Z",
                "timezone": "UTC",
                "latitude": 51.5074,
                "longitude": -0.1278,
                "satellite_id": "SAT-BULK-001"
            },
            {
                "timestamp": "2025-12-07T13:00:00Z",
                "timezone": "UTC",
                "latitude": 48.8566,
                "longitude": 2.3522,
                "satellite_id": "SAT-BULK-002"
            }
        ]
        response = client.post("/api/observations/bulk", headers=auth_headers, json=bulk_data)
        assert response.status_code == 201
        assert len(response.json["created"]) == 2
        assert len(response.json["errors"]) == 0

    def test_bulk_create_partial_success(self, client, auth_headers):
        """Test bulk creation with some errors"""
        bulk_data = [
            {
                "timestamp": "2025-12-07T12:00:00Z",
                "timezone": "UTC",
                "latitude": 51.5074,
                "longitude": -0.1278,
                "satellite_id": "SAT-VALID"
            },
            {
                "timestamp": "invalid-date",
                "timezone": "UTC",
                "latitude": 48.8566,
                "longitude": 2.3522,
                "satellite_id": "SAT-INVALID"
            }
        ]
        response = client.post("/api/observations/bulk", headers=auth_headers, json=bulk_data)
        assert response.status_code == 207  # Multi-status
        assert len(response.json["created"]) == 1
        assert len(response.json["errors"]) == 1

    def test_bulk_create_not_array(self, client, auth_headers):
        """Test bulk creation with non-array payload"""
        response = client.post(
            "/api/observations/bulk",
            headers=auth_headers,
            json={"not": "an array"}
        )
        assert response.status_code == 400

    def test_bulk_update_success(self, client, auth_headers, sample_observation_data):
        """Test bulk update of observations"""
        # Create observations first
        create1 = client.post("/api/observations", headers=auth_headers, json=sample_observation_data)
        id1 = create1.json["id"]
        
        data2 = sample_observation_data.copy()
        data2["satellite_id"] = "SAT-TEST-002"
        create2 = client.post("/api/observations", headers=auth_headers, json=data2)
        id2 = create2.json["id"]
        
        # Bulk update
        bulk_update = [
            {
                "id": id1,
                "notes": "Bulk updated 1"
            },
            {
                "id": id2,
                "notes": "Bulk updated 2"
            }
        ]
        response = client.patch("/api/observations/bulk", headers=auth_headers, json=bulk_update)
        assert response.status_code == 200
        assert len(response.json["updated"]) == 2
        assert len(response.json["errors"]) == 0

    def test_bulk_update_missing_id(self, client, auth_headers):
        """Test bulk update with missing ID"""
        bulk_update = [
            {
                "notes": "Missing ID"
            }
        ]
        response = client.patch("/api/observations/bulk", headers=auth_headers, json=bulk_update)
        assert response.status_code == 207
        assert len(response.json["errors"]) == 1

    def test_bulk_update_nonexistent_id(self, client, auth_headers):
        """Test bulk update with non-existent ID"""
        bulk_update = [
            {
                "id": 99999,
                "notes": "Non-existent"
            }
        ]
        response = client.patch("/api/observations/bulk", headers=auth_headers, json=bulk_update)
        assert response.status_code == 207
        assert len(response.json["errors"]) == 1
        assert "NOT_FOUND" in response.json["errors"][0]["error"]


# ============================================================================
# OpenAPI/Documentation Tests
# ============================================================================

class TestDocumentation:
    def test_openapi_json(self, client):
        """Test OpenAPI specification endpoint"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert "openapi" in response.json
        assert response.json["info"]["title"] == "Geospatial Intelligence API"

    def test_swagger_ui(self, client):
        """Test Swagger UI endpoint"""
        response = client.get("/docs")
        assert response.status_code == 200
        assert b"swagger-ui" in response.data.lower()


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    def test_method_not_allowed(self, client, auth_headers):
        """Test method not allowed error"""
        response = client.put("/health", headers=auth_headers)
        assert response.status_code == 405

    def test_invalid_json(self, client, auth_headers):
        """Test invalid JSON payload"""
        response = client.post(
            "/api/observations",
            headers={"Authorization": auth_headers["Authorization"], "Content-Type": "application/json"},
            data="invalid json{"
        )
        assert response.status_code in [400, 500]  # Depends on Flask version


# ============================================================================
# Run Configuration
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])




# import pytest
# import os
# from app import app
# from dotenv import load_dotenv

# load_dotenv()

# @pytest.fixture
# def client():
#     return app.test_client()

# @pytest.fixture
# def django_token():
#     token = os.getenv("DJANGO_TEST_TOKEN")
#     assert token, "Missing DJANGO_TEST_TOKEN environment variable."
#     return token

# @pytest.fixture
# def headers(django_token):
#     return {
#         "Authorization": f"Bearer {django_token}",
#         "Content-Type": "application/json"
#     }

# def test_health_check(client):
#     response = client.get("/health")
#     assert response.status_code == 200
#     assert response.json["status"] == "ok"

# def test_unauthorized_access(client):
#     response = client.get("/api/observations")
#     assert response.status_code == 401

# def test_create_observation(client, headers):
#     data = {
#         "timestamp": "2025-12-07T12:00:00Z",
#         "timezone": "UTC",
#         "latitude": 51.5074,
#         "longitude": -0.1278,
#         "satellite_id": "SAT-DJANGO-TEST",
#         "notes": "Created via pytest"
#     }
#     response = client.post("/api/observations", headers=headers, json=data)
#     assert response.status_code == 201
#     assert response.json["satellite_id"] == "SAT-DJANGO-TEST"



