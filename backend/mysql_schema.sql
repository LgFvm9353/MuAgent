-- Harness Agent System - MySQL 8 initial schema
-- Safe initialization: this script does not drop databases or tables.

CREATE DATABASE IF NOT EXISTS `agent`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `agent`;

CREATE TABLE IF NOT EXISTS `conversations` (
    `id` CHAR(32) NOT NULL,
    `title` VARCHAR(255) NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_conversations_updated_at` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `tasks` (
    `id` CHAR(32) NOT NULL,
    `conversation_id` CHAR(32) NOT NULL,
    `originating_invocation_id` CHAR(32) NULL,
    `trace_id` CHAR(32) NOT NULL,
    `state` VARCHAR(32) NOT NULL,
    `contract` JSON NOT NULL,
    `version` INT NOT NULL,
    `cancel_requested` BOOLEAN NOT NULL,
    `updated_at` DATETIME(6) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_tasks_originating_invocation_id` (`originating_invocation_id`),
    KEY `ix_tasks_conversation_id` (`conversation_id`),
    KEY `ix_tasks_originating_invocation_id` (`originating_invocation_id`),
    KEY `ix_tasks_trace_id` (`trace_id`),
    KEY `ix_tasks_state` (`state`),
    KEY `ix_tasks_state_updated` (`state`, `updated_at`),
    CONSTRAINT `fk_tasks_conversation_id`
        FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `conversation_turns` (
    `id` CHAR(32) NOT NULL,
    `conversation_id` CHAR(32) NOT NULL,
    `idempotency_key` CHAR(32) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `collaboration_mode` VARCHAR(32) NOT NULL DEFAULT 'parallel',
    `collaboration_phase` VARCHAR(32) NOT NULL DEFAULT 'routing',
    `synthesize` BOOLEAN NOT NULL DEFAULT FALSE,
    `lead_agent_id` VARCHAR(100) NULL,
    `lease_owner` VARCHAR(100) NULL,
    `lease_expires_at` DATETIME(6) NULL,
    `last_activity_at` DATETIME(6) NULL,
    `failure_reason` VARCHAR(100) NULL,
    `requires_execution` BOOLEAN NOT NULL DEFAULT FALSE,
    `task_id` CHAR(32) NULL,
    `completed_at` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_conversation_turns_conversation_idempotency`
        (`conversation_id`, `idempotency_key`),
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
    KEY `ix_routing_decisions_turn_id` (`turn_id`),
    CONSTRAINT `fk_routing_decisions_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- source_message_id is indexed but intentionally has no foreign key here. Omitting the
-- reverse edge keeps this initialization script rerunnable without cyclic ALTER TABLE steps.
CREATE TABLE IF NOT EXISTS `handoff_records` (
    `id` CHAR(32) NOT NULL,
    `turn_id` CHAR(32) NOT NULL,
    `source_agent_id` VARCHAR(100) NOT NULL,
    `target_agent_id` VARCHAR(100) NOT NULL,
    `intent` VARCHAR(32) NOT NULL DEFAULT 'delegate',
    `objective` VARCHAR(4000) NOT NULL,
    `context_summary` VARCHAR(4000) NOT NULL,
    `source_message_id` BIGINT NULL,
    `parent_handoff_id` CHAR(32) NULL,
    `completed_message_id` BIGINT NULL,
    `depth` INT NOT NULL DEFAULT 0,
    `status` VARCHAR(32) NOT NULL,
    `rejection_reason` VARCHAR(255) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    KEY `ix_handoff_records_turn_id` (`turn_id`),
    KEY `ix_handoff_records_source_message_id` (`source_message_id`),
    KEY `ix_handoff_records_parent_handoff_id` (`parent_handoff_id`),
    KEY `ix_handoff_records_completed_message_id` (`completed_message_id`),
    CONSTRAINT `fk_handoff_records_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_handoff_records_parent_handoff_id`
        FOREIGN KEY (`parent_handoff_id`) REFERENCES `handoff_records` (`id`) ON DELETE SET NULL
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

-- Optional source_message_id, handoff_id and task_id references intentionally have no
-- foreign keys in this rerunnable bootstrap schema. They remain indexed trace IDs;
-- Alembic migrations may add stricter constraints in managed installations.
CREATE TABLE IF NOT EXISTS `agent_invocation_queue` (
    `id` CHAR(32) NOT NULL,
    `conversation_id` CHAR(32) NOT NULL,
    `turn_id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NULL,
    `source_agent_id` VARCHAR(100) NULL,
    `target_agent_id` VARCHAR(100) NOT NULL,
    `source_message_id` BIGINT NULL,
    `handoff_id` CHAR(32) NULL,
    `parent_invocation_id` CHAR(32) NULL,
    `intent` VARCHAR(32) NOT NULL,
    `objective` VARCHAR(4000) NOT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
    `depth` INT NOT NULL DEFAULT 0,
    `attempt` INT NOT NULL DEFAULT 0,
    `priority` INT NOT NULL DEFAULT 0,
    `dedup_key` VARCHAR(64) NOT NULL,
    `lease_owner` VARCHAR(100) NULL,
    `lease_expires_at` DATETIME(6) NULL,
    `available_at` DATETIME(6) NOT NULL,
    `started_at` DATETIME(6) NULL,
    `completed_at` DATETIME(6) NULL,
    `error_type` VARCHAR(100) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_agent_invocation_queue_dedup_key` (`dedup_key`),
    KEY `ix_agent_invocation_queue_conversation_id` (`conversation_id`),
    KEY `ix_agent_invocation_queue_turn_id` (`turn_id`),
    KEY `ix_agent_invocation_queue_task_id` (`task_id`),
    KEY `ix_agent_invocation_queue_source_message_id` (`source_message_id`),
    KEY `ix_agent_invocation_queue_handoff_id` (`handoff_id`),
    KEY `ix_agent_invocation_queue_parent_invocation_id` (`parent_invocation_id`),
    KEY `ix_invocation_queue_claim`
        (`conversation_id`, `target_agent_id`, `status`, `available_at`),
    CONSTRAINT `fk_agent_invocation_queue_conversation_id`
        FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_agent_invocation_queue_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_agent_invocation_queue_parent_invocation_id`
        FOREIGN KEY (`parent_invocation_id`) REFERENCES `agent_invocation_queue` (`id`)
        ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agent_runs` (
    `id` CHAR(32) NOT NULL,
    `task_id` CHAR(32) NULL,
    `turn_id` CHAR(32) NULL,
    `handoff_id` CHAR(32) NULL,
    `invocation_queue_entry_id` CHAR(32) NULL,
    `parent_run_id` CHAR(32) NULL,
    `intent` VARCHAR(32) NULL,
    `phase` VARCHAR(32) NULL,
    `role` VARCHAR(32) NULL,
    `skill_id` VARCHAR(64) NULL,
    `skill_version` VARCHAR(32) NULL,
    `skill_hash` VARCHAR(64) NULL,
    `tool_rounds` INT NOT NULL DEFAULT 0,
    `tool_calls` INT NOT NULL DEFAULT 0,
    `resume_state` JSON NULL,
    `attempt` INT NOT NULL DEFAULT 1,
    `lease_owner` VARCHAR(100) NULL,
    `lease_expires_at` DATETIME(6) NULL,
    `last_activity_at` DATETIME(6) NULL,
    `agent_id` VARCHAR(100) NOT NULL,
    `prompt_version` VARCHAR(64) NOT NULL,
    `schema_version` VARCHAR(64) NOT NULL,
    `model` VARCHAR(100) NOT NULL,
    `config_hash` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `output` JSON NULL,
    `error_type` VARCHAR(100) NULL,
    `started_at` DATETIME(6) NULL,
    `completed_at` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_agent_runs_invocation_queue_entry_id` (`invocation_queue_entry_id`),
    KEY `ix_agent_runs_task_id` (`task_id`),
    KEY `ix_agent_runs_turn_id` (`turn_id`),
    KEY `ix_agent_runs_handoff_id` (`handoff_id`),
    KEY `ix_agent_runs_invocation_queue_entry_id` (`invocation_queue_entry_id`),
    KEY `ix_agent_runs_parent_run_id` (`parent_run_id`),
    CONSTRAINT `fk_agent_runs_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_agent_runs_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_agent_runs_handoff_id`
        FOREIGN KEY (`handoff_id`) REFERENCES `handoff_records` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_agent_runs_invocation_queue_entry_id`
        FOREIGN KEY (`invocation_queue_entry_id`) REFERENCES `agent_invocation_queue` (`id`)
        ON DELETE SET NULL,
    CONSTRAINT `fk_agent_runs_parent_run_id`
        FOREIGN KEY (`parent_run_id`) REFERENCES `agent_runs` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `conversation_messages` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `task_id` CHAR(32) NULL,
    `conversation_id` CHAR(32) NULL,
    `turn_id` CHAR(32) NULL,
    `agent_run_id` CHAR(32) NULL,
    `routing_decision_id` CHAR(32) NULL,
    `handoff_id` CHAR(32) NULL,
    `reply_to_message_id` BIGINT NULL,
    `agent_id` VARCHAR(100) NOT NULL,
    `role` VARCHAR(32) NOT NULL,
    `message_type` VARCHAR(64) NOT NULL,
    `phase` VARCHAR(64) NOT NULL,
    `summary` VARCHAR(1000) NOT NULL,
    `content` JSON NOT NULL,
    `mentions` JSON NOT NULL,
    `routing_metadata` JSON NOT NULL,
    `source_id` VARCHAR(100) NOT NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_conversation_messages_task_source` (`task_id`, `source_id`),
    KEY `ix_conversation_messages_task_id` (`task_id`),
    KEY `ix_conversation_messages_conversation_id` (`conversation_id`),
    KEY `ix_conversation_messages_turn_id` (`turn_id`),
    KEY `ix_conversation_messages_agent_run_id` (`agent_run_id`),
    KEY `ix_conversation_messages_routing_decision_id` (`routing_decision_id`),
    KEY `ix_conversation_messages_handoff_id` (`handoff_id`),
    KEY `ix_conversation_messages_reply_to_message_id` (`reply_to_message_id`),
    CONSTRAINT `fk_conversation_messages_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_conversation_messages_conversation_id`
        FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_conversation_messages_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_conversation_messages_agent_run_id`
        FOREIGN KEY (`agent_run_id`) REFERENCES `agent_runs` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_conversation_messages_routing_decision_id`
        FOREIGN KEY (`routing_decision_id`) REFERENCES `routing_decisions` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_conversation_messages_handoff_id`
        FOREIGN KEY (`handoff_id`) REFERENCES `handoff_records` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_conversation_messages_reply_to_message_id`
        FOREIGN KEY (`reply_to_message_id`) REFERENCES `conversation_messages` (`id`) ON DELETE SET NULL
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
    `task_id` CHAR(32) NULL,
    `step_id` CHAR(32) NULL,
    `turn_id` CHAR(32) NULL,
    `agent_run_id` CHAR(32) NULL,
    `tool_name` VARCHAR(255) NOT NULL,
    `idempotency_key` VARCHAR(64) NOT NULL,
    `status` VARCHAR(32) NOT NULL,
    `source` VARCHAR(32) NOT NULL DEFAULT 'local',
    `server_id` VARCHAR(100) NULL,
    `risk` VARCHAR(32) NOT NULL DEFAULT 'low',
    `arguments` JSON NOT NULL,
    `arguments_hash` VARCHAR(64) NULL,
    `schema_hash` VARCHAR(64) NULL,
    `output_hash` VARCHAR(64) NULL,
    `attempt` INT NOT NULL DEFAULT 1,
    `timeout_seconds` DOUBLE NULL,
    `side_effect_state` VARCHAR(32) NULL,
    `result` JSON NULL,
    `error_type` VARCHAR(100) NULL,
    `started_at` DATETIME(6) NULL,
    `completed_at` DATETIME(6) NULL,
    `created_at` DATETIME(6) NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_tool_calls_idempotency_key` (`idempotency_key`),
    KEY `ix_tool_calls_task_id` (`task_id`),
    KEY `ix_tool_calls_step_id` (`step_id`),
    KEY `ix_tool_calls_turn_id` (`turn_id`),
    KEY `ix_tool_calls_agent_run_id` (`agent_run_id`),
    CONSTRAINT `fk_tool_calls_task_id`
        FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_tool_calls_step_id`
        FOREIGN KEY (`step_id`) REFERENCES `execution_steps` (`id`),
    CONSTRAINT `fk_tool_calls_turn_id`
        FOREIGN KEY (`turn_id`) REFERENCES `conversation_turns` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_tool_calls_agent_run_id`
        FOREIGN KEY (`agent_run_id`) REFERENCES `agent_runs` (`id`) ON DELETE SET NULL
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
SELECT '0005_mention_execution'
WHERE NOT EXISTS (
    SELECT 1
    FROM `alembic_version`
);

UPDATE `alembic_version`
SET `version_num` = '0005_mention_execution'
WHERE `version_num` IN (
    '0001_initial',
    '0002_conversations',
    '0003_multi_agent_conversations',
    '0003_tool_governance',
    '0004_agent_invocation_queue'
);
