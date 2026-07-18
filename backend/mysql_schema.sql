-- Harness Agent System - MySQL 8 initial schema
-- Safe initialization: this script does not drop databases or tables.

CREATE DATABASE IF NOT EXISTS `agent`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `agent`;

CREATE TABLE IF NOT EXISTS `tasks` (
    `id` CHAR(32) NOT NULL,
    `trace_id` CHAR(32) NOT NULL,
    `state` VARCHAR(32) NOT NULL,
    `contract` JSON NOT NULL,
    `version` INT NOT NULL,
    `cancel_requested` BOOLEAN NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_tasks_trace_id` (`trace_id`),
    KEY `ix_tasks_state` (`state`),
    KEY `ix_tasks_state_updated` (`state`, `updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `task_events` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `task_id` CHAR(32) NOT NULL,
    `event_type` VARCHAR(64) NOT NULL,
    `from_state` VARCHAR(32) NULL,
    `to_state` VARCHAR(32) NULL,
    `payload` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_task_events_task_id` (`task_id`),
    CONSTRAINT `fk_task_events_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agent_runs` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `agent_id` VARCHAR(100) NOT NULL,
    `prompt_version` VARCHAR(64) NOT NULL,
    `schema_version` VARCHAR(64) NOT NULL,
    `model` VARCHAR(100) NOT NULL,
    `config_hash` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `output` JSON NULL,
    `error_type` VARCHAR(100) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_agent_runs_task_id` (`task_id`),
    CONSTRAINT `fk_agent_runs_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `conversation_messages` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `task_id` CHAR(32) NOT NULL,
    `agent_id` VARCHAR(100) NOT NULL,
    `role` VARCHAR(32) NOT NULL,
    `message_type` VARCHAR(64) NOT NULL,
    `phase` VARCHAR(64) NOT NULL,
    `summary` VARCHAR(1000) NOT NULL,
    `content` JSON NOT NULL,
    `source_id` VARCHAR(100) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_conversation_messages_task_source` (`task_id`, `source_id`),
    KEY `ix_conversation_messages_task_id` (`task_id`),
    CONSTRAINT `fk_conversation_messages_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `proposals` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `agent_run_id` CHAR(32) NOT NULL,
    `version` INT NOT NULL,
    `content` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_proposals_task_id` (`task_id`),
    KEY `ix_proposals_agent_run_id` (`agent_run_id`),
    CONSTRAINT `fk_proposals_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_proposals_agent_run_id`
        FOREIGN KEY (`agent_run_id`) REFERENCES `agent_runs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `execution_plans` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `version` INT NOT NULL,
    `content` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_execution_plans_task_version` (`task_id`, `version`),
    KEY `ix_execution_plans_task_id` (`task_id`),
    CONSTRAINT `fk_execution_plans_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `execution_steps` (
    `id` CHAR(32) NOT NULL,
    `plan_id` CHAR(32) NOT NULL,
    `step_key` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `content` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_execution_steps_plan_step` (`plan_id`, `step_key`),
    KEY `ix_execution_steps_plan_id` (`plan_id`),
    CONSTRAINT `fk_execution_steps_plan_id`
        FOREIGN KEY (`plan_id`) REFERENCES `execution_plans` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `tool_calls` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `step_id` CHAR(32) NOT NULL,
    `tool_name` VARCHAR(100) NOT NULL,
    `idempotency_key` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `arguments` JSON NOT NULL,
    `result` JSON NULL,
    `error_type` VARCHAR(100) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_tool_calls_idempotency_key` (`idempotency_key`),
    KEY `ix_tool_calls_task_id` (`task_id`),
    KEY `ix_tool_calls_step_id` (`step_id`),
    CONSTRAINT `fk_tool_calls_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_tool_calls_step_id`
        FOREIGN KEY (`step_id`) REFERENCES `execution_steps` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `confirmations` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `plan_id` CHAR(32) NOT NULL,
    `call_hash` VARCHAR(64) NOT NULL,
    `approved` BOOLEAN NOT NULL,
    `decided_by` VARCHAR(100) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_confirmations_task_plan_hash` (`task_id`, `plan_id`, `call_hash`),
    KEY `ix_confirmations_task_id` (`task_id`),
    KEY `ix_confirmations_plan_id` (`plan_id`),
    CONSTRAINT `fk_confirmations_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_confirmations_plan_id`
        FOREIGN KEY (`plan_id`) REFERENCES `execution_plans` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `evidence_records` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `step_id` CHAR(32) NOT NULL,
    `kind` VARCHAR(64) NOT NULL,
    `content` JSON NOT NULL,
    `sha256` VARCHAR(64) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_evidence_records_task_id` (`task_id`),
    KEY `ix_evidence_records_step_id` (`step_id`),
    CONSTRAINT `fk_evidence_records_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_evidence_records_step_id`
        FOREIGN KEY (`step_id`) REFERENCES `execution_steps` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `verification_reports` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `plan_id` CHAR(32) NOT NULL,
    `verdict` VARCHAR(32) NOT NULL,
    `content` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_verification_reports_task_id` (`task_id`),
    KEY `ix_verification_reports_plan_id` (`plan_id`),
    CONSTRAINT `fk_verification_reports_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_verification_reports_plan_id`
        FOREIGN KEY (`plan_id`) REFERENCES `execution_plans` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `audit_events` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `task_id` CHAR(32) NULL,
    `trace_id` CHAR(32) NOT NULL,
    `event_type` VARCHAR(100) NOT NULL,
    `payload` JSON NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_audit_events_task_id` (`task_id`),
    KEY `ix_audit_events_trace_id` (`trace_id`),
    CONSTRAINT `fk_audit_events_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `usage_records` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NOT NULL,
    `agent_run_id` CHAR(32) NOT NULL,
    `request_id` VARCHAR(100) NULL,
    `model` VARCHAR(100) NOT NULL,
    `stop_reason` VARCHAR(64) NULL,
    `input_tokens` INT NOT NULL,
    `output_tokens` INT NOT NULL,
    `cache_creation_input_tokens` INT NOT NULL,
    `cache_read_input_tokens` INT NOT NULL,
    `latency_ms` INT NOT NULL,
    `retry_count` INT NOT NULL,
    `estimated_cost_usd` DOUBLE NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_usage_records_task_id` (`task_id`),
    KEY `ix_usage_records_agent_run_id` (`agent_run_id`),
    KEY `ix_usage_records_request_id` (`request_id`),
    CONSTRAINT `fk_usage_records_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_usage_records_agent_run_id`
        FOREIGN KEY (`agent_run_id`) REFERENCES `agent_runs` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `alembic_version` (
    `version_num` VARCHAR(32) NOT NULL,
    PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `alembic_version` (`version_num`)
SELECT '0001_initial'
WHERE NOT EXISTS (
    SELECT 1
    FROM `alembic_version`
    WHERE `version_num` = '0001_initial'
);
