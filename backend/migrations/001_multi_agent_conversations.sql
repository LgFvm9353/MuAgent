-- Multi-Agent conversation vertical slice migration (MySQL 8)
-- Apply once after mysql_schema.sql. This migration is additive and preserves task history.

USE `agent`;

CREATE TABLE IF NOT EXISTS `conversation_turns` (
    `id` CHAR(32) NOT NULL,
    `conversation_id` CHAR(32) NOT NULL,
    `idempotency_key` CHAR(32) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `requires_execution` BOOLEAN NOT NULL DEFAULT FALSE,
    `task_id` CHAR(32) NULL,
    `completed_at` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_conversation_turn_idempotency` (`conversation_id`, `idempotency_key`),
    KEY `ix_conversation_turns_conversation_id` (`conversation_id`),
    KEY `ix_conversation_turns_task_id` (`task_id`),
    CONSTRAINT `fk_conversation_turns_conversation_id`
        FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_conversation_turns_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `routing_decisions` (
    `id` CHAR(32) NOT NULL,
    `turn_id` CHAR(32) NOT NULL,
    `source` VARCHAR(32) NOT NULL,
    `selected_agents` JSON NOT NULL,
    `confidence` DOUBLE NOT NULL,
    `reason_code` VARCHAR(100) NOT NULL,
    `mentions` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_routing_decisions_turn_id` (`turn_id`),
    CONSTRAINT `fk_routing_decisions_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `handoff_records` (
    `id` CHAR(32) NOT NULL,
    `turn_id` CHAR(32) NOT NULL,
    `source_agent_id` VARCHAR(100) NOT NULL,
    `target_agent_id` VARCHAR(100) NOT NULL,
    `objective` VARCHAR(1000) NOT NULL,
    `context_summary` VARCHAR(4000) NOT NULL,
    `source_message_id` BIGINT NULL,
    `status` VARCHAR(32) NOT NULL,
    `rejection_reason` VARCHAR(255) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_handoff_records_turn_id` (`turn_id`),
    CONSTRAINT `fk_handoff_records_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE `agent_runs`
    MODIFY COLUMN `task_id` CHAR(32) NULL,
    ADD COLUMN `turn_id` CHAR(32) NULL AFTER `task_id`,
    ADD COLUMN `handoff_id` CHAR(32) NULL AFTER `turn_id`,
    ADD COLUMN `started_at` DATETIME(6) NULL,
    ADD COLUMN `completed_at` DATETIME(6) NULL,
    ADD KEY `ix_agent_runs_turn_id` (`turn_id`),
    ADD KEY `ix_agent_runs_handoff_id` (`handoff_id`),
    ADD CONSTRAINT `fk_agent_runs_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    ADD CONSTRAINT `fk_agent_runs_handoff_id`
        FOREIGN KEY (`handoff_id`) REFERENCES `handoff_records` (`id`) ON DELETE SET NULL;

ALTER TABLE `conversation_messages`
    MODIFY COLUMN `task_id` CHAR(32) NULL,
    ADD COLUMN `conversation_id` CHAR(32) NULL AFTER `task_id`,
    ADD COLUMN `turn_id` CHAR(32) NULL AFTER `conversation_id`,
    ADD COLUMN `agent_run_id` CHAR(32) NULL AFTER `turn_id`,
    ADD COLUMN `routing_decision_id` CHAR(32) NULL AFTER `agent_run_id`,
    ADD COLUMN `handoff_id` CHAR(32) NULL AFTER `routing_decision_id`,
    ADD COLUMN `reply_to_message_id` BIGINT NULL AFTER `handoff_id`,
    ADD COLUMN `mentions` JSON NULL,
    ADD COLUMN `routing_metadata` JSON NULL,
    ADD KEY `ix_conversation_messages_conversation_id` (`conversation_id`),
    ADD KEY `ix_conversation_messages_turn_id` (`turn_id`),
    ADD KEY `ix_conversation_messages_agent_run_id` (`agent_run_id`),
    ADD CONSTRAINT `fk_conversation_messages_conversation_id`
        FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
    ADD CONSTRAINT `fk_conversation_messages_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    ADD CONSTRAINT `fk_conversation_messages_agent_run_id`
        FOREIGN KEY (`agent_run_id`) REFERENCES `agent_runs` (`id`) ON DELETE SET NULL;

UPDATE `conversation_messages` AS message
JOIN `tasks` AS task ON task.`id` = message.`task_id`
SET message.`conversation_id` = task.`conversation_id`,
    message.`mentions` = JSON_ARRAY(),
    message.`routing_metadata` = JSON_OBJECT()
WHERE message.`conversation_id` IS NULL;

UPDATE `conversation_messages`
SET `mentions` = JSON_ARRAY()
WHERE `mentions` IS NULL;

UPDATE `conversation_messages`
SET `routing_metadata` = JSON_OBJECT()
WHERE `routing_metadata` IS NULL;

ALTER TABLE `conversation_messages`
    MODIFY COLUMN `mentions` JSON NOT NULL,
    MODIFY COLUMN `routing_metadata` JSON NOT NULL;
