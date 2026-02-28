---
name: learn-generate-asyncapi
description: Read an async/event-driven codebase and generate a valid static AsyncAPI 2.6 YAML spec, stored as a file with a summary note.
---

Generate an AsyncAPI 2.6 specification for the event-driven / message-driven integration surface in the current repo.

## Supported transports

Cover all of the following if present in the codebase:

- **RabbitMQ / AMQP 0-9-1** — exchanges, queues, routing keys, consumers, producers
- **Kafka** — topics, consumer groups, producers
- **MQTT** — topics, QoS levels
- **WebSocket** — channels, message schemas
- **Server-Sent Events (SSE)** — event streams
- **Any other pub/sub or message-passing system visible in the source**

## Default Acceptance Criteria

Apply these criteria to every channel and message in the spec. Do not skip or approximate any of them:

- Every channel must have: a channel address (the queue name, topic name, or URL path pattern), at least one operation (`send` or `receive`), and a `messages` reference — never an inline anonymous message where a name can be inferred.
- Every message must have: a `name`, a `title` (human-readable), a `summary` (one sentence), a `contentType` (`application/json` unless the source says otherwise), and a `payload` schema with all known fields typed and annotated `required` / optional.
- All reusable message schemas must be declared under `components/messages` and referenced via `$ref` — never duplicated inline.
- All reusable payload schemas must be declared under `components/schemas` and referenced via `$ref`.
- Every channel must use the correct **protocol binding** for its transport:
  - AMQP: `bindings.amqp` with `is` (`routingKey` or `queue`), `exchange` (name, type, durable, autoDelete, vhost) and `queue` (name, durable, exclusive, autoDelete) as applicable.
  - Kafka: `bindings.kafka` with `topic`, `partitions`, `replicas` where known.
  - MQTT: `bindings.mqtt` with `qos`, `retain` where known.
  - WebSocket: `bindings.ws` with `method` and `query` where applicable.
- Every operation (`send` / `receive`) must have: `operationId` (camelCase, globally unique), `summary` (one sentence), and `tags` (at least one). `send` = this service publishes; `receive` = this service consumes.
- All known enum values must be listed explicitly (`enum: [...]`) — no free-form strings where a fixed set is visible in the source.
- Any field, parameter, or behaviour whose type or optionality is ambiguous must be annotated with `x-ambiguous: true` and an inline comment explaining the uncertainty.
- The spec must use AsyncAPI 2.6.0 — not 3.x, not 2.4 or earlier. The document must begin with `asyncapi: "2.6.0"`.

## Language-specific discovery hints

Use these patterns to locate async integration points. Read the actual source — do not guess based on file names alone.

### Java / Spring Boot
- `@RabbitListener(queues = "...")` — consumer; extract queue name and message type
- `@KafkaListener(topics = "...")` — consumer
- `RabbitTemplate.convertAndSend(exchange, routingKey, payload)` — producer
- `KafkaTemplate.send(topic, payload)` — producer
- `@Bean Queue`, `@Bean TopicExchange`, `@Bean DirectExchange`, `@Bean Binding` — exchange/queue declarations
- `@StreamListener`, `@Input`, `@Output` (Spring Cloud Stream) — channel bindings
- `MessageConverter` implementations — message payload shape
- DTO / POJO classes passed to `convertAndSend` or received in `@RabbitListener` methods — payload schema

### Python
- `pika.channel.basic_consume`, `pika.channel.basic_publish` — consumer / producer
- `aio_pika.Queue.consume`, `aio_pika.Exchange.publish` — async consumer / producer
- `kombu.Consumer`, `kombu.Producer` — Celery-style
- `aiokafka.AIOKafkaConsumer`, `aiokafka.AIOKafkaProducer` — Kafka
- `Pydantic` models passed as message payloads — payload schema

### Node.js / TypeScript
- `amqplib` / `amqplib/callback_api` — `channel.consume`, `channel.publish`, `channel.assertQueue`, `channel.assertExchange`
- `kafkajs` — `consumer.run`, `producer.send`
- `mqtt.subscribe`, `mqtt.publish`

### Go
- `amqp.Channel.Consume`, `amqp.Channel.Publish` (github.com/rabbitmq/amqp091-go)
- `sarama.Consumer`, `sarama.SyncProducer`

## Steps

1. Identify the current repo:
   - Run `git rev-parse --show-toplevel` to get the repo root.
   - Extract the repo name.

2. Detect the primary language(s) and build tools present (`pom.xml`, `build.gradle`, `package.json`, `go.mod`, `pyproject.toml`, `requirements.txt`, etc.).

3. Discover all async integration surfaces using the language-specific hints above. For each surface, record:
   - **Direction**: producer (send) or consumer (receive)
   - **Transport**: AMQP, Kafka, MQTT, WebSocket, SSE, etc.
   - **Channel address**: queue name, topic name, exchange+routingKey pattern
   - **Exchange declaration** (AMQP): name, type (direct/topic/fanout/headers), durable, autoDelete
   - **Queue declaration** (AMQP): name, durable, exclusive, autoDelete
   - **Message payload schema**: all fields with types, required/optional
   - **Consumer group** (Kafka): if declared
   - **Any headers, correlation IDs, or metadata fields** attached to the message

4. Generate a complete AsyncAPI 2.6.0 YAML document applying all acceptance criteria above.

   Minimum required structure:
   ```yaml
   asyncapi: "2.6.0"
   info:
     title: <service name>
     version: "1.0.0"
     description: <one paragraph>
   servers:
     production:
       url: <broker URL if known, otherwise a placeholder like amqp://rabbitmq:5672>
       protocol: amqp  # or kafka, mqtt, ws, etc.
       description: <environment description>
   channels:
     <queue-or-topic-name>:
       description: <what flows through this channel>
       bindings:
         amqp:
           is: queue  # or routingKey
           queue:
             name: <queue name>
             durable: true
             exclusive: false
             autoDelete: false
           exchange:
             name: <exchange name>
             type: direct  # direct | topic | fanout | headers
             durable: true
             autoDelete: false
             vhost: /
       subscribe:  # this service consumes from this channel
         operationId: <camelCase unique ID>
         summary: <one sentence>
         tags:
           - name: <domain tag>
         message:
           $ref: '#/components/messages/<MessageName>'
   components:
     messages:
       <MessageName>:
         name: <MessageName>
         title: <Human Readable Title>
         summary: <one sentence>
         contentType: application/json
         payload:
           $ref: '#/components/schemas/<PayloadName>'
     schemas:
       <PayloadName>:
         type: object
         required: [field1, field2]
         properties:
           field1:
             type: string
             description: <description>
           field2:
             type: integer
             description: <description>
   ```

   Use `subscribe` when this service **receives** messages on that channel.
   Use `publish` when this service **sends** messages on that channel.
   (AsyncAPI 2.x uses the server's perspective: `subscribe` = server subscribes = service is the consumer.)

5. Write the YAML to a temporary file:
   ```bash
   cat > /tmp/<repo-name>-asyncapi.yaml << 'EOF'
   <yaml content>
   EOF
   ```
   Then base64-encode it:
   ```bash
   base64 -w 0 /tmp/<repo-name>-asyncapi.yaml
   ```

6. Call `store_file` with:
   - `name`: `asyncapi/<repo-name>.yaml`
   - `content_base64`: the base64 string from step 5
   - `mime_type`: `application/yaml`
   - `tags`: `asyncapi,events,<repo-name>,<transport>` (replace `<transport>` with e.g. `amqp`, `kafka`, `mqtt`)

7. Call `store_note` with:
   - `key`: `asyncapi/<repo-name>`
   - `body`: a markdown summary containing:
     - One-line description of what the service does in the async domain
     - Primary protocol(s) in use (AMQP, Kafka, etc.)
     - Total number of channels documented
     - List of all operationIds (each on its own line, with direction: producer/consumer)
     - Any items flagged with `x-ambiguous: true` and the uncertainty description
     - Reference line: "Full spec stored at file `asyncapi/<repo-name>.yaml`"
   - `tags`: `asyncapi,events,<repo-name>,<transport>`

8. Confirm to the user: "Stored AsyncAPI spec as `asyncapi/<repo-name>.yaml` and summary note as `asyncapi/<repo-name>`."

## Notes on AsyncAPI 2.x vs 3.x

This skill targets **2.6.0** (the last stable 2.x release, supported by all current tooling including AsyncAPI Studio, AsyncAPI Generator, and Microcks). AsyncAPI 3.0 changed the channel/operation model significantly — do not generate 3.0 output unless the user explicitly requests it.
