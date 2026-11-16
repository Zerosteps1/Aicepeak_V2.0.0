# Multistep dockerfile
#
# 1. build the frontend
# 2. copy the built frontend and build the backend with it
# 3. copy the output into the runtime
#
# The 3. step is done to minimize size
#
# always copy lockfile first then install dependencies only THEN the code,
# to have faster builds as docker caches every step,
# and as dependencies change less often than code, this speeds things up

# 1) Frontend: node builds dist/ (node 26, as in the factory's test image)
FROM node:26-bookworm-slim AS frontend
ARG VITE_ENTRA_CLIENT_ID
ARG VITE_ENTRA_API_SCOPE
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2) Backend: the SDK publishes the API; npm is skipped
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS backend
WORKDIR /src
COPY global.json ./
COPY backend/Aicepeak.Api.csproj backend/packages.lock.json backend/Directory.Build.props \
     backend/Directory.Packages.props backend/nuget.config \
     backend/
RUN dotnet restore backend/Aicepeak.Api.csproj --locked-mode
COPY backend/ backend/
RUN dotnet publish backend/Aicepeak.Api.csproj -c Release -o /app --no-restore -p:SkipFrontendBuild=true

# 3) Runtime: ASP.NET runtime only, the frontend as wwwroot
FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=backend /app ./
COPY --from=frontend /src/frontend/dist ./wwwroot
USER $APP_UID
EXPOSE 8080
ENTRYPOINT ["dotnet", "Aicepeak.Api.dll"]
