# Aicepeak image: the API with the built frontend in wwwroot. One image for every environment:
# ENTRA_* and DB_* come from the environment at start (docker run --env-file), never from the build.
# Build from the repository root:  docker build -f backend/Dockerfile -t aicepeak .

# 1. Frontend. index.html keeps its config placeholder; the backend fills it at startup.
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# 2. Backend, restored from the committed lock files.
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS backend
WORKDIR /src
COPY global.json ./
COPY backend/ backend/
RUN dotnet restore backend/Aicepeak.Api.csproj --locked-mode
RUN dotnet publish backend/Aicepeak.Api.csproj -c Release -o /app --no-restore -p:SkipFrontendBuild=true

# 3. Runtime.
FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=backend /app ./
COPY --from=frontend /src/frontend/dist ./wwwroot
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
USER app
ENTRYPOINT ["dotnet", "Aicepeak.Api.dll"]
