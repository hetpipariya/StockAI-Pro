# Stage 1: Build
FROM node:18-alpine as builder

WORKDIR /app

# Install dependencies based on package-lock.json if available
COPY package*.json ./
RUN npm ci || npm install

# Copy source and build
COPY . .
RUN npm run build

# Stage 2: Serve (Nginx handles routing, this container just serves the static built files to to the root nginx)
# Wait, actually the root Nginx will proxy / to this container if it runs its own nginx.
FROM nginx:alpine

# Copy built assets to Nginx html directory
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port (default for nginx image is 80)
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
