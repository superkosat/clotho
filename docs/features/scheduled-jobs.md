# Scheduled Jobs

Jobs run agent prompts on a cron schedule and deliver responses to Discord channels or DMs.

## Defining a Job

Create YAML files in `~/.clotho/jobs/`:

```yaml
name: daily-standup
enabled: true

trigger:
  type: cron
  expression: "0 9 * * 1-5"    # 9 AM weekdays (5-field cron)

prompt: "Generate a daily standup report."

delivery:
  - type: discord_channel
    channel_id: "123456789"
  - type: discord_dm
    user_id: "987654321"
```

## Trigger Types

Currently supported: `cron` with a standard 5-field cron expression.

## Delivery Types

| Type | Fields | Description |
|---|---|---|
| `discord_channel` | `channel_id` | Post to a server channel |
| `discord_dm` | `user_id` | Send a DM to a user |

## Behaviour

- The scheduler loads jobs on gateway startup and rescans the jobs directory for changes
- Each job maintains its own persistent chat session — context accumulates across runs
- Set `enabled: false` to pause a job without deleting it
- Tool calls in scheduled jobs are auto-approved (no interactive approval possible)
