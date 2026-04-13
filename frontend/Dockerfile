# ====================================================================
# STOCKAI PRO - Frontend Dockerfile (React + Vite + Nginx)
# Optimized for production with multi-stage build
# ====================================================================

# ========== STAGE 1: BUILD ==========
# Build React + Vite application
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install all dependencies (including devDependencies for build)
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Verify build output
RUN ls -la dist/ && echo "Build completed successfully"


# ========== STAGE 2: RUNTIME ==========
# Serve static files with minimal Nginx image
FROM nginx:1.25-alpine

# ========== Set labels for Docker metadata ==========
LABEL maintainer="StockAI Pro Team"
LABEL description="StockAI Pro Frontend - React + Vite served by Nginx"
LABEL version="1.0.0"

# Copy nginx configuration with proper defaults
COPY <<EOF /etc/nginx/conf.d/default.conf
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # ========== Security Headers ==========
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Permissions-Policy "accelerometer=(), camera=(), microphone=(), geolocation=()" always;

    # ========== GZIP Compression ==========
    gzip on;
    gzip_vary on;
    gzip_types text/plain text/css text/javascript application/json application/javascript;
    gzip_comp_level 6;
    gzip_min_length 1000;

    # ========== Performance ==========
    client_max_body_size 10M;
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
    
    # ========== Root directory ==========
    root /usr/share/nginx/html;
    index index.html index.htm;

    # ========== Static files with caching ==========
    location ~* \.(js|css|woff|woff2|ttf|eot|svg|png|jpg|jpeg|gif|ico)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # ========== SPA routing: fallback to index.html ==========
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        expires 0;
    }

    # ========== Health check endpoint ==========
    location /health {
        access_log off;
        return 200 "Frontend is healthy\n";
        add_header Content-Type text/plain;
    }

    # ========== Deny access to sensitive files ==========
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
EOF

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose HTTP port
EXPOSE 80

# ========== Build info ==========
RUN echo "Frontend image built at $(date)" > /usr/share/nginx/html/build-info.txt

# ========== Health check ==========
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]

