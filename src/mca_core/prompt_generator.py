import re
import os


# Path sanitization for privacy - VULN-003 fix
def _sanitize_path(text: str) -> str:
    """脱敏文件系统路径，防止用户个人信息泄露到 AI API。

    Args:
        text: 可能包含文件路径的文本

    Returns:
        脱敏后的文本
    """
    # 替换 Windows 绝对路径中的用户名部分
    text = re.sub(r'C:\\Users\\[^\\]+', r'C:\\Users\\<user>', text)
    # 替换 Unix 家目录路径
    text = re.sub(r'/home/[^/\s]+', r'/home/<user>', text)
    # 替换 .minecraft 路径中的盘符
    text = re.sub(r'[A-Z]:\\(?:Users\\[^\\]+\\AppData\\Roaming\\)?\.minecraft', r'<mc_dir>', text)
    return text


_RE_FORGE_MOD = re.compile(r'^U[CHIJE]*\s+[a-zA-Z0-9_\-]+')
_RE_FABRIC_MOD = re.compile(r'^\t- [a-zA-Z0-9_\-]+@')


class PromptGenerator:
    """
    Tier 3: The "Doctor's Note" / AI Prompt Generator
    Sanitizes and compresses massive logs into a high-quality Markdown prompt.
    
    隐私保护: 所有文件系统路径在发送前自动脱敏。
    """
    
    @staticmethod
    def generate_prompt(crash_log: str, local_diagnosis: str = "") -> str:
        # VULN-003: 先脱敏再提取
        sanitized_log = _sanitize_path(crash_log)
        
        # Extract Crash Stack Trace
        stack_trace = PromptGenerator._extract_stack_trace(sanitized_log)
        
        # Extract Java/MC Version details
        sys_info = PromptGenerator._extract_system_info(sanitized_log)
        
        # Extract Mod List (truncated if too long)
        mod_list = PromptGenerator._extract_mod_list(sanitized_log)
        
        local_diag_section = ""
        if local_diagnosis.strip():
            local_diag_section = f"\n### Local Scanner Diagnosis\n{local_diagnosis.strip()}\n"
        
        prompt = f"""Please act as a Minecraft crash diagnosis expert. I have a crash issue.

### System Environment
{sys_info}{local_diag_section}

### Crash Stack Trace
```java
{stack_trace}
```

### Loaded Mods
```text
{mod_list}
```

Please analyze this crash and tell me:
1. The exact mod(s) causing the issue.
2. The root cause of the crash.
3. Steps to fix it (e.g., removing a mod, updating a mod, changing config).
"""
        return prompt.strip()

    @staticmethod
    def _extract_stack_trace(log: str) -> str:
        # VULN-004 修复: 添加 {1,50} 上限防止 ReDoS
        # Look for typical crash stack starts
        match = re.search(
            r'(?:java\.lang\.[A-Za-z]+Exception|net\.minecraft\.crash\.ReportedException|java\.lang\.Error)[^\n]*\n(?:\s*at .+\n){1,50}',
            log, re.MULTILINE
        )
        if match:
            stack = match.group(0).strip()
            # truncate to 30 lines
            lines = stack.split('\n')
            if len(lines) > 30:
                stack = '\n'.join(lines[:30]) + '\n... [truncated]'
            return stack
        return "No specific stack trace found."

    @staticmethod
    def _extract_system_info(log: str) -> str:
        info = []
        # Find MC version
        mc_ver = re.search(r'Minecraft Version: (.*)', log)
        if mc_ver:
            info.append(f"- Minecraft Version: {mc_ver.group(1)}")
            
        # Find Java version
        java_ver = re.search(r'Java Version: (.*)', log)
        if java_ver:
            info.append(f"- Java Version: {java_ver.group(1)}")
            
        # Mod loader
        if "Forge" in log or "FML" in log:
            info.append("- Mod Loader: Forge")
        elif "Fabric" in log:
            info.append("- Mod Loader: Fabric")
            
        if not info:
            return "System info not found."
        return '\n'.join(info)

    @staticmethod
    def _extract_mod_list(log: str) -> str:
        # Very simplified mod list extraction
        # Look for lines containing typical mod list formats
        mods = []
        for line in log.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if "A detailed walkthrough of the error" in line_stripped:
                continue
            if _RE_FORGE_MOD.match(line_stripped):
                mods.append(line_stripped)
            elif _RE_FABRIC_MOD.match(line_stripped):
                mods.append(line_stripped)
                
        if mods:
            if len(mods) > 50:
                return '\n'.join(mods[:50]) + f'\n... and {len(mods)-50} more.'
            return '\n'.join(mods)
        return "Mod list not found."
