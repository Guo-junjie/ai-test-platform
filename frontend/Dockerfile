FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json ./
# 官方 node 镜像默认 NODE_ENV=production，会导致 npm install 跳过 devDependencies（vue-tsc/vite/typescript 均不安装）。
# 构建阶段必须显式带上 dev 依赖，否则 npm run build 报 "vue-tsc: not found"。
RUN npm install --include=dev

COPY . .

# 赋予 node_modules/.bin 目录下所有脚本可执行权限
RUN chmod +x node_modules/.bin/*

RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
