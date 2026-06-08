import re
from typing import List, Dict, Any, Optional

from mca_core.regex_cache import RegexCache


class CrashPatternLibrary:
    def __init__(self):
        self.patterns: List[Dict[str, Any]] = [
            {
                "id": "geckolib_animation",
                "name": "GeckoLib 动画错误",
                "keywords": ["software.bernie.geckolib", "AnimationController", "NullPointerException"],
                "advice": "GeckoLib 动画控制器发生空指针异常。通常是由于实体模型或动画文件缺失/损坏导致。尝试更新 GeckoLib 或移除报错实体所属的模组。"
            },
            {
                "id": "mixin_injection",
                "name": "Mixin 注入失败",
                "keywords": ["org.spongepowered.asm.mixin.transformer.MixinProcessor", "InjectionError", "Critical injection failure"],
                "advice": "Mixin 注入失败。这通常意味着两个模组试图修改同一段代码并发生冲突。检查日志中提到的 'Target' 类和 'Handler' 方法，找出冲突的模组。"
            },
            {
                "id": "tessellator_crash",
                "name": "Tessellator 渲染错误",
                "keywords": ["net.minecraft.client.renderer.Tessellator", "BufferBuilder", "Not tessellating"],
                "advice": "Tessellator 状态异常。通常由渲染类模组（如 OptiFine, Sodium, Canvas）引起。尝试禁用这些模组或调整渲染设置。"
            },
            {
                "id": "glfw_error",
                "name": "GLFW 窗口/输入错误",
                "keywords": ["org.lwjgl.glfw.GLFW", "GLFW error", "Pixel format not accelerated"],
                "advice": "GLFW 底层错误。可能是显卡驱动过旧、不支持 OpenGL 版本或被其他软件（如录屏软件、覆盖层）干扰。更新显卡驱动或关闭后台干扰软件。"
            },
            {
                "id": "registry_overflow",
                "name": "注册表溢出",
                "keywords": ["Registry", "maximum id range", "exceeded", "too many entries"],
                "advice": "模组注册表超出ID范围限制。通常安装了太多模组或在1.12.2及更早版本中遇到。尝试使用 JEID、NotEnoughIDs 等扩展模组，或移除部分模组。"
            },
            {
                "id": "config_error",
                "name": "配置文件错误",
                "keywords": ["Config", "malformed", "cannot parse", "invalid entry", "configuration error"],
                "advice": "配置文件损坏或格式错误。删除对应模组的配置文件让其重新生成，或手动检查 JSON/TOML 语法错误。"
            },
            {
                "id": "network_protocol",
                "name": "网络协议错误",
                "keywords": ["Packet", "decoder", "serializer", "NetworkRegistry", "payload too large", "protocol error"],
                "advice": "网络数据包序列化/反序列化错误。通常是客户端和服务器模组版本不一致，或某个模组注册了错误的数据包处理器。"
            },
            {
                "id": "forge_loader",
                "name": "Forge 加载器错误",
                "keywords": ["net.minecraftforge.fml", "LoadingFailedException", "ModLoadingException", "FMLCommonLaunchHandler"],
                "advice": "Forge/FML 加载器在加载模组时遇到错误。检查是否有模组版本与当前 Forge 版本不兼容，或尝试逐个移除模组排查。"
            },
            {
                "id": "fabric_loader",
                "name": "Fabric 加载器错误",
                "keywords": ["net.fabricmc.loader", "FabricLoader", "entrypoint", "LanguageAdapter"],
                "advice": "Fabric Loader 加载模组失败。检查模组是否与该 Fabric Loader 版本兼容，或尝试移除最近添加的模组。"
            },
            {
                "id": "access_violation",
                "name": "内存访问违规",
                "keywords": ["EXCEPTION_ACCESS_VIOLATION", "access violation", "0x00000000", "native code"],
                "advice": "JVM 发生内存访问违规 (Access Violation)。通常由显卡驱动、Java 版本不兼容或第三方 DLL 注入导致。更新显卡驱动和 Java 版本，关闭后台注入软件。"
            },
            {
                "id": "stack_overflow",
                "name": "栈溢出",
                "keywords": ["StackOverflowError", "stack overflow", "recursion"],
                "advice": "栈溢出错误。通常是某个模组中的递归调用失控或无限循环导致。检查日志中的调用链，找出重复调用的方法。"
            },
            {
                "id": "class_cast",
                "name": "类型转换错误",
                "keywords": ["ClassCastException", "cannot be cast", "cannot cast"],
                "advice": "类型转换异常。通常是某个模组对 Minecraft 实体/方块/物品进行了不兼容的类型替换。检查日志中涉及的类名。"
            },
            {
                "id": "null_pointer",
                "name": "空指针异常",
                "keywords": ["NullPointerException", "Cannot invoke", "because \"", "is null"],
                "advice": "空指针异常 (NullPointerException)。某个模组访问了未初始化的对象。检查日志中 'at' 处的类名以定位问题模组。"
            },
            {
                "id": "concurrent_mod",
                "name": "并发修改异常",
                "keywords": ["ConcurrentModificationException", "concurrent modification"],
                "advice": "并发修改异常。某个模组在遍历集合时修改了集合内容。这通常是模组代码的 Bug，建议向模组作者报告。"
            },
            {
                "id": "no_such_method",
                "name": "方法缺失错误",
                "keywords": ["NoSuchMethodError", "no such method", "method not found"],
                "advice": "方法缺失错误 (NoSuchMethodError)。模组尝试调用不存在的方法，通常是模组版本与 Minecraft/Loader 版本不兼容导致。"
            },
            {
                "id": "illegal_argument",
                "name": "非法参数错误",
                "keywords": ["IllegalArgumentException", "illegal argument", "invalid argument"],
                "advice": "非法参数异常。某个模组向方法传入了无效的参数值。检查日志中涉及的类和方法。"
            },
            {
                "id": "file_not_found",
                "name": "文件未找到",
                "keywords": ["FileNotFoundException", "no such file", "cannot find file", "resource not found"],
                "advice": "文件/资源未找到。模组尝试加载不存在的文件或资源。可能是模组安装不完整，或资源包/数据包路径配置错误。"
            },
            {
                "id": "socket_error",
                "name": "网络连接错误",
                "keywords": ["SocketException", "ConnectException", "connection refused", "connection timed out", "host unreachable"],
                "advice": "网络连接错误。通常是服务器未启动、防火墙阻止连接或认证服务器不可用。检查网络设置和服务器状态。"
            },
            {
                "id": "memory_leak",
                "name": "内存泄漏警告",
                "keywords": ["memory leak", "leaking", "can't keep up", "running behind", "skipping"],
                "advice": "服务器性能警告或内存泄漏。可能是 Tick 耗时过长或内存使用不当。尝试减少模组数量、优化 JVM 参数或增加内存分配。"
            },
            {
                "id": "datapack_error",
                "name": "数据包错误",
                "keywords": ["datapack", "data pack", "failed to load pack", "pack.mcmeta"],
                "advice": "数据包加载失败。检查数据包格式是否正确，pack.mcmeta 文件是否存在且格式有效。"
            },
        ]

    def match(self, log_content: Optional[str]) -> List[Dict[str, Any]]:
        if log_content is None:
            return []
        
        matches = []
        log_lower = log_content.lower()
        
        for pattern in self.patterns:
            score = 0
            keywords = pattern["keywords"]
            
            for kw in keywords:
                try:
                    if RegexCache.search(re.escape(kw), log_content, flags=re.IGNORECASE):
                        score += 1
                except re.error:
                    if kw.lower() in log_lower:
                        score += 1
            
            if score >= 2:
                matches.append({
                    "id": pattern["id"],
                    "name": pattern["name"],
                    "advice": pattern["advice"]
                })
            elif score == 1 and len(keywords) == 1:
                matches.append({
                    "id": pattern["id"],
                    "name": pattern["name"],
                    "advice": pattern["advice"]
                })
                
        return matches
