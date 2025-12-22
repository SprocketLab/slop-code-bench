# Comprehensive API Documentation Guide

## Table of Contents

1. [Introduction](#introduction)
2. [Authentication](#authentication)
3. [Base URL and Endpoints](#base-url-and-endpoints)
4. [Common Response Formats](#common-response-formats)
5. [Error Handling](#error-handling)
6. [Rate Limiting](#rate-limiting)
7. [API Endpoints](#api-endpoints)
   - [Users](#users)
   - [Products](#products)
   - [Orders](#orders)
   - [Payments](#payments)
   - [Analytics](#analytics)
8. [Webhooks](#webhooks)
9. [SDKs and Libraries](#sdks-and-libraries)
10. [Best Practices](#best-practices)
11. [Changelog](#changelog)

## Introduction

Welcome to the comprehensive REST API documentation for our e-commerce platform. This API provides programmatic access to all platform functionality including user management, product catalog, order processing, payment handling, and analytics.

### Key Features

- **RESTful Architecture**: Clean, intuitive API design following REST principles
- **JSON Responses**: Consistent JSON format for all responses
- **Authentication**: Secure OAuth 2.0 and JWT-based authentication
- **Pagination**: Efficient pagination for large datasets
- **Rate Limiting**: Fair usage policies with configurable limits
- **Webhooks**: Real-time event notifications
- **Comprehensive Testing**: Full test coverage with sandbox environment

### Getting Started

1. [Register for an API key](https://developer.example.com/register)
2. [Review authentication methods](#authentication)
3. [Test with our sandbox environment](https://sandbox-api.example.com)
4. [Integrate with our SDKs](#sdks-and-libraries)

## Authentication

### OAuth 2.0 Flow

We support the standard OAuth 2.0 authorization code flow for web applications:

```http
GET https://api.example.com/oauth/authorize?
    response_type=code&
    client_id=YOUR_CLIENT_ID&
    redirect_uri=YOUR_REDIRECT_URI&
    scope=read+write&
    state=RANDOM_STRING
```

#### Exchange Authorization Code for Access Token

```http
POST https://api.example.com/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&
code=AUTHORIZATION_CODE&
redirect_uri=YOUR_REDIRECT_URI&
client_id=YOUR_CLIENT_ID&
client_secret=YOUR_CLIENT_SECRET
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "def50200e3b4...",
  "scope": "read write"
}
```

### JWT Authentication

For server-to-server communication, use JWT tokens:

```http
POST https://api.example.com/auth/jwt
Content-Type: application/json

{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET"
}
```

### API Key Authentication

For simple integrations, you can use API keys:

```http
GET https://api.example.com/v1/products
X-API-Key: YOUR_API_KEY
```

## Base URL and Endpoints

### Production Environment
```
https://api.example.com
```

### Sandbox Environment
```
https://sandbox-api.example.com
```

### API Versioning
We use URL-based versioning. Current version: `v1`

```
https://api.example.com/v1/users
https://api.example.com/v2/users  # Future version
```

## Common Response Formats

### Success Response

```json
{
  "success": true,
  "data": {
    // Response data here
  },
  "meta": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "req_123456789",
    "version": "1.0"
  }
}
```

### Paginated Response

```json
{
  "success": true,
  "data": [
    // Array of items
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 150,
    "total_pages": 8,
    "has_next": true,
    "has_prev": false
  },
  "links": {
    "first": "https://api.example.com/v1/products?page=1",
    "last": "https://api.example.com/v1/products?page=8",
    "next": "https://api.example.com/v1/products?page=2",
    "prev": null
  }
}
```

## Error Handling

### Error Response Format

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request parameters",
    "details": [
      {
        "field": "email",
        "message": "Invalid email format"
      }
    ]
  },
  "meta": {
    "timestamp": "2024-01-15T10:30:00Z",
    "request_id": "req_123456789"
  }
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Request validation failed |
| `UNAUTHORIZED` | 401 | Authentication required |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `CONFLICT` | 409 | Resource conflict |
| `RATE_LIMITED` | 429 | Rate limit exceeded |
| `INTERNAL_ERROR` | 500 | Internal server error |

## Rate Limiting

### Rate Limit Headers

```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1642248000
```

### Rate Limits by Plan

| Plan | Requests/Hour | Burst Limit |
|------|---------------|-------------|
| Free | 1,000 | 100 |
| Basic | 10,000 | 500 |
| Pro | 100,000 | 2,000 |
| Enterprise | Unlimited | 10,000 |

## API Endpoints

### Users

#### Create User

```http
POST https://api.example.com/v1/users
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "email": "user@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "password": "secure_password",
  "phone": "+1234567890"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "user_123456",
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone": "+1234567890",
    "status": "active",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-01-15T10:30:00Z"
  }
}
```

#### Get User

```http
GET https://api.example.com/v1/users/{user_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### Update User

```http
PUT https://api.example.com/v1/users/{user_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "first_name": "Jane",
  "last_name": "Smith"
}
```

#### List Users

```http
GET https://api.example.com/v1/users?page=1&per_page=20&status=active
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### Delete User

```http
DELETE https://api.example.com/v1/users/{user_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
```

### Products

#### Create Product

```http
POST https://api.example.com/v1/products
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "name": "Premium Laptop",
  "description": "High-performance laptop with 16GB RAM",
  "price": 1299.99,
  "category_id": "cat_123",
  "sku": "LAPTOP-001",
  "inventory_count": 100,
  "images": [
    "https://example.com/images/laptop1.jpg",
    "https://example.com/images/laptop2.jpg"
  ],
  "attributes": {
    "color": "Silver",
    "weight": "2.5kg",
    "warranty": "2 years"
  }
}
```

#### Get Product

```http
GET https://api.example.com/v1/products/{product_id}
```

#### Search Products

```http
GET https://api.example.com/v1/products/search?q=laptop&category=electronics&min_price=500&max_price=2000&sort=price_asc
```

#### Update Product

```http
PUT https://api.example.com/v1/products/{product_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "price": 1199.99,
  "inventory_count": 85
}
```

#### Delete Product

```http
DELETE https://api.example.com/v1/products/{product_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
```

### Orders

#### Create Order

```http
POST https://api.example.com/v1/orders
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "user_id": "user_123456",
  "items": [
    {
      "product_id": "prod_789",
      "quantity": 2,
      "price": 1299.99
    },
    {
      "product_id": "prod_790",
      "quantity": 1,
      "price": 29.99
    }
  ],
  "shipping_address": {
    "street": "123 Main St",
    "city": "New York",
    "state": "NY",
    "zip_code": "10001",
    "country": "USA"
  },
  "payment_method": "credit_card"
}
```

#### Get Order

```http
GET https://api.example.com/v1/orders/{order_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### List Orders

```http
GET https://api.example.com/v1/orders?user_id=user_123456&status=completed&page=1
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### Update Order Status

```http
PUT https://api.example.com/v1/orders/{order_id}/status
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "status": "shipped",
  "tracking_number": "TRK123456789",
  "notes": "Shipped via UPS Ground"
}
```

### Payments

#### Process Payment

```http
POST https://api.example.com/v1/payments
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "order_id": "order_456789",
  "amount": 2629.97,
  "currency": "USD",
  "payment_method": {
    "type": "credit_card",
    "card_number": "4242424242424242",
    "expiry_month": "12",
    "expiry_year": "2025",
    "cvv": "123",
    "holder_name": "John Doe"
  },
  "billing_address": {
    "street": "123 Main St",
    "city": "New York",
    "state": "NY",
    "zip_code": "10001",
    "country": "USA"
  }
}
```

#### Get Payment

```http
GET https://api.example.com/v1/payments/{payment_id}
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### Refund Payment

```http
POST https://api.example.com/v1/payments/{payment_id}/refund
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "amount": 100.00,
  "reason": "Customer requested refund"
}
```

### Analytics

#### Get Sales Report

```http
GET https://api.example.com/v1/analytics/sales?start_date=2024-01-01&end_date=2024-01-31&group_by=day
Authorization: Bearer YOUR_ACCESS_TOKEN
```

**Response:**
```json
{
  "success": true,
  "data": {
    "period": {
      "start_date": "2024-01-01",
      "end_date": "2024-01-31"
    },
    "summary": {
      "total_sales": 125000.50,
      "total_orders": 450,
      "average_order_value": 277.78,
      "conversion_rate": 3.2
    },
    "daily_breakdown": [
      {
        "date": "2024-01-01",
        "sales": 3250.00,
        "orders": 12,
        "unique_customers": 10
      }
    ]
  }
}
```

#### Get Product Analytics

```http
GET https://api.example.com/v1/analytics/products?top_selling=true&limit=10
Authorization: Bearer YOUR_ACCESS_TOKEN
```

#### Get Customer Analytics

```http
GET https://api.example.com/v1/analytics/customers?segment=returning&cohort=2024-01
Authorization: Bearer YOUR_ACCESS_TOKEN
```

## Webhooks

### Configure Webhook

```http
POST https://api.example.com/v1/webhooks
Authorization: Bearer YOUR_ACCESS_TOKEN
Content-Type: application/json

{
  "url": "https://your-app.com/webhooks",
  "events": [
    "order.created",
    "order.completed",
    "payment.succeeded",
    "payment.failed"
  ],
  "secret": "your_webhook_secret"
}
```

### Webhook Event Format

```json
{
  "event": "order.created",
  "data": {
    "order_id": "order_456789",
    "user_id": "user_123456",
    "total_amount": 2629.97,
    "currency": "USD",
    "status": "pending"
  },
  "timestamp": "2024-01-15T10:30:00Z",
  "signature": "sha256=5d41402abc4b2a76b9719d911017c592"
}
```

### Verify Webhook Signature

```python
import hmac
import hashlib

def verify_webhook_signature(payload, signature, secret):
    expected_signature = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(f"sha256={expected_signature}", signature)
```

## SDKs and Libraries

### Official SDKs

#### Python

```bash
pip install example-api-client
```

```python
from example_api import ExampleAPI

client = ExampleAPI(api_key="YOUR_API_KEY")

# Create a user
user = client.users.create(
    email="user@example.com",
    first_name="John",
    last_name="Doe"
)

# Create an order
order = client.orders.create(
    user_id=user.id,
    items=[
        {"product_id": "prod_123", "quantity": 1}
    ]
)
```

#### JavaScript/Node.js

```bash
npm install example-api-client
```

```javascript
const ExampleAPI = require('example-api-client');

const client = new ExampleAPI({ apiKey: 'YOUR_API_KEY' });

// Create a user
const user = await client.users.create({
  email: 'user@example.com',
  firstName: 'John',
  lastName: 'Doe'
});

// Create an order
const order = await client.orders.create({
  userId: user.id,
  items: [
    { productId: 'prod_123', quantity: 1 }
  ]
});
```

#### Ruby

```bash
gem install example-api-client
```

```ruby
require 'example_api'

client = ExampleAPI::Client.new(api_key: 'YOUR_API_KEY')

# Create a user
user = client.users.create(
  email: 'user@example.com',
  first_name: 'John',
  last_name: 'Doe'
)

# Create an order
order = client.orders.create(
  user_id: user.id,
  items: [
    { product_id: 'prod_123', quantity: 1 }
  ]
)
```

## Best Practices

### 1. Authentication
- Use HTTPS for all API calls
- Store API keys securely (environment variables, secret management)
- Implement token refresh logic for OAuth
- Use short-lived tokens with refresh mechanism

### 2. Error Handling
- Always check the `success` field in responses
- Implement exponential backoff for rate limits
- Log error responses with request IDs for debugging
- Handle network timeouts gracefully

### 3. Performance
- Use pagination for large datasets
- Implement caching for frequently accessed data
- Use appropriate HTTP methods (GET for reads, POST for creates)
- Compress request/response bodies when possible

### 4. Security
- Validate all input data before processing
- Use webhook signature verification
- Implement rate limiting on your side
- Monitor API usage for anomalies

### 5. Testing
- Use sandbox environment for development
- Write integration tests for critical workflows
- Test error scenarios and edge cases
- Monitor API status and availability

## Changelog

### Version 1.2.0 (2024-01-15)
- Added bulk operations for products and orders
- Enhanced search with fuzzy matching
- New analytics endpoints for customer segmentation
- Improved webhook reliability with retry logic

### Version 1.1.0 (2023-12-01)
- Introduced JWT authentication
- Added inventory management endpoints
- Enhanced error messages with field-level details
- Performance improvements for large datasets

### Version 1.0.0 (2023-10-01)
- Initial public release
- Core CRUD operations for users, products, orders
- OAuth 2.0 authentication
- Basic analytics endpoints
- Webhook support

## Support

- **Documentation**: https://docs.example.com
- **API Status**: https://status.example.com
- **Support Email**: api-support@example.com
- **Community Forum**: https://community.example.com
- **GitHub Issues**: https://github.com/example/api/issues

## License

This API is subject to our [Terms of Service](https://example.com/terms) and [API License Agreement](https://example.com/api-license). Please review these documents before integrating with our platform.

---

*Last updated: January 15, 2024*