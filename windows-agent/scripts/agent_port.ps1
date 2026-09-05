$AgentPort = [int]((Get-Content (Join-Path $PSScriptRoot "..\config\agent_port.txt") -Raw).Trim())
