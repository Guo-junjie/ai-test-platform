FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json ./
# 国内构建环境网络受限，走 npmmirror 镜像源（与后端 pip 阿里源同理），
# 否则 npm install 可能卡在 <30kB/s 的国际链路上
RUN npm config set registry https://registry.npmmirror.com && npm install --include=dev

COPY . .

# 赋予 node_modules/.bin 目录下所有脚本可执行权限
RUN chmod +x node_modules/.bin/*

RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
