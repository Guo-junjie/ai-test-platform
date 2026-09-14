package demo;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

/** 常驻 Java HTTP 服务：用不同请求验证 JaCoCo 的测试窗口隔离。 */
public final class OrderService {
    private OrderService() {}

    public static void main(String[] args) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("0.0.0.0", 8204), 0);
        server.createContext("/health", exchange -> respond(exchange, 200, "ok"));
        server.createContext("/orders/", exchange -> {
            if ("/orders/1".equals(exchange.getRequestURI().getPath())) {
                respond(exchange, 200, "{\"id\":1,\"state\":\"paid\"}");
            } else {
                respond(exchange, 404, "{\"error\":\"not found\"}");
            }
        });
        server.start();
    }

    private static void respond(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }
}
