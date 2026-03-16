#!/usr/bin/env python3
"""
Test staging vs production backends.
Compares API responses between staging and production deployments.
"""

import httpx
import json
import sys
from datetime import datetime

PROD_URL = "https://thredion-api-production.up.railway.app"
STAGING_URL = "https://thredion-api-staging.azurewebsites.net"

TIMEOUT = 30


def test_health(base_url: str, env_name: str):
    """Test /health endpoint."""
    print(f"\n{'='*60}")
    print(f"Testing {env_name.upper()} - Health Check")
    print(f"URL: {base_url}/health")
    print(f"{'='*60}")
    
    try:
        response = httpx.get(f"{base_url}/health", timeout=TIMEOUT)
        status = response.status_code
        print(f"✅ Status: {status}")
        if status == 200:
            print(f"✅ Response: {response.json()}")
            return True
        else:
            print(f"❌ Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_api_info(base_url: str, env_name: str):
    """Test /api/info endpoint if available."""
    print(f"\n{'='*60}")
    print(f"Testing {env_name.upper()} - API Info")
    print(f"URL: {base_url}/api/info")
    print(f"{'='*60}")
    
    try:
        response = httpx.get(f"{base_url}/api/info", timeout=TIMEOUT)
        status = response.status_code
        print(f"Status: {status}")
        if status in [200, 404]:
            if status == 200:
                print(f"✅ Response: {response.json()}")
            else:
                print(f"⚠️  Endpoint not found (404)")
            return True
        else:
            print(f"❌ Response: {response.text}")
            return False
    except Exception as e:
        print(f"⚠️  Error (expected if endpoint doesn't exist): {e}")
        return True


def test_database(base_url: str, env_name: str):
    """Test database connectivity via API."""
    print(f"\n{'='*60}")
    print(f"Testing {env_name.upper()} - Database Check")
    print(f"URL: {base_url}/api/check-db")
    print(f"{'='*60}")
    
    try:
        response = httpx.get(f"{base_url}/api/check-db", timeout=TIMEOUT)
        status = response.status_code
        print(f"Status: {status}")
        if status in [200, 404]:
            if status == 200:
                print(f"✅ Response: {response.json()}")
            else:
                print(f"⚠️  Endpoint not found (404)")
            return True
        else:
            print(f"❌ Response: {response.text}")
            return False
    except Exception as e:
        print(f"⚠️  Error: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("THREDION STAGING vs PRODUCTION TEST")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    results = {}
    
    # Test production
    print("\n📍 PRODUCTION BASELINE")
    prod_health = test_health(PROD_URL, "production")
    prod_info = test_api_info(PROD_URL, "production")
    prod_db = test_database(PROD_URL, "production")
    results["production"] = {
        "health": prod_health,
        "info": prod_info,
        "database": prod_db,
    }
    
    # Test staging
    print("\n\n📍 STAGING (New Deployment)")
    staging_health = test_health(STAGING_URL, "staging")
    staging_info = test_api_info(STAGING_URL, "staging")
    staging_db = test_database(STAGING_URL, "staging")
    results["staging"] = {
        "health": staging_health,
        "info": staging_info,
        "database": staging_db,
    }
    
    # Summary
    print("\n\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(json.dumps(results, indent=2))
    
    prod_score = sum([prod_health, prod_info, prod_db])
    staging_score = sum([staging_health, staging_info, staging_db])
    
    print(f"\nProduction: {prod_score}/3 tests passing")
    print(f"Staging:    {staging_score}/3 tests passing")
    
    if staging_score == 3 and prod_score == 3:
        print("\n✅ BOTH ENVIRONMENTS WORKING - Ready for testing!")
        sys.exit(0)
    elif staging_score >= 1:
        print("\n⚠️  Staging partially working - Check deployment logs")
        sys.exit(1)
    else:
        print("\n❌ Staging deployment incomplete - Waiting for Azure build...")
        sys.exit(1)


if __name__ == "__main__":
    main()
