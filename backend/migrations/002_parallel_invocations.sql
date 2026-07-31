-- Explicit parallel agent invocation orchestration (MySQL 8)
USE `agent`;

CREATE TABLE IF NOT EXISTS `parallel_invocation_requests` (
    `id` CHAR(32) NOT NULL,
    `conversation_id` CHAR(32) NOT NULL,
    `turn_id` CHAR(32) NOT NULL,
    `source_message_id` BIGINT NOT NULL,
    `initiator_agent_id` VARCHAR(100) NOT NULL,
    `callback_agent_id` VARCHAR(100) NOT NULL,
    `targets` JSON NOT NULL,
    `question` VARCHAR(4000) NOT NULL,
    `context` VARCHAR(4000) NOT NULL,
    `idempotency_key` CHAR(32) NOT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
    `deadline_at` DATETIME(6) NOT NULL,
    `aggregated_message_id` BIGINT NULL,
    `completed_at` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_parallel_request_idempotency` (`conversation_id`, `idempotency_key`),
    KEY `ix_parallel_request_turn` (`turn_id`),
    KEY `ix_parallel_request_deadline` (`status`, `deadline_at`),
    CONSTRAINT `fk_parallel_request_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_parallel_request_turn` FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_parallel_request_source_message` FOREIGN KEY (`source_message_id`) REFERENCES `conversation_messages` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_parallel_request_aggregate` FOREIGN KEY (`aggregated_message_id`) REFERENCES `conversation_messages` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `parallel_invocation_responses` (
    `id` CHAR(32) NOT NULL,
    `request_id` CHAR(32) NOT NULL,
    `target_agent_id` VARCHAR(100) NOT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
    `content` JSON NULL,
    `error_type` VARCHAR(100) NULL,
    `completed_at` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_parallel_response_target` (`request_id`, `target_agent_id`),
    KEY `ix_parallel_response_request` (`request_id`),
    CONSTRAINT `fk_parallel_response_request` FOREIGN KEY (`request_id`) REFERENCES `parallel_invocation_requests` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `agent_invocation_queue`
    ADD COLUMN `parallel_request_id` CHAR(32) NULL AFTER `handoff_id`,
    ADD COLUMN `parallel_response_id` CHAR(32) NULL AFTER `parallel_request_id`,
    ADD KEY `ix_invocation_queue_parallel_request` (`parallel_request_id`),
    ADD UNIQUE KEY `uq_invocation_queue_parallel_response` (`parallel_response_id`),
    ADD CONSTRAINT `fk_invocation_queue_parallel_request` FOREIGN KEY (`parallel_request_id`) REFERENCES `parallel_invocation_requests` (`id`) ON DELETE SET NULL,
    ADD CONSTRAINT `fk_invocation_queue_parallel_response` FOREIGN KEY (`parallel_response_id`) REFERENCES `parallel_invocation_responses` (`id`) ON DELETE SET NULL;
