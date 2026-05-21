import os
import zipfile
import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class PackageMapper:
    """
    Tier 2: Package Mapper
    Maps stack trace packages (e.g., 'com.github.tartaricacid') directly to local `.jar` file names.
    Solves mod conflicts by finding which JAR contains the offending class.
    """
    
    def __init__(self, mods_dir: str):
        self.mods_dir = mods_dir
        # Cache of package -> jar filename
        # e.g., 'com/github/tartaricacid' -> 'touhou_little_maid-1.16.5-1.2.3.jar'
        self._package_cache: Dict[str, str] = {}
        self._is_indexed = False
        
    def index_mods(self) -> None:
        """Scan all JAR files in the mods directory and map top-level packages."""
        if not os.path.isdir(self.mods_dir):
            logger.warning(f"Mods directory not found: {self.mods_dir}")
            return
            
        logger.info("Indexing mods for Package Mapping...")
        for filename in os.listdir(self.mods_dir):
            if not filename.endswith('.jar'):
                continue
                
            filepath = os.path.join(self.mods_dir, filename)
            try:
                with zipfile.ZipFile(filepath, 'r') as zf:
                    for name in zf.namelist():
                        if name.endswith('.class'):
                            # get the package directory structure
                            # 'com/github/tartaricacid/EntityMaid.class' -> 'com/github/tartaricacid'
                            package_path = os.path.dirname(name)
                            if package_path and package_path not in ('net/minecraft', 'net/fabricmc', 'net/minecraftforge'):
                                if package_path not in self._package_cache:
                                    self._package_cache[package_path] = filename
            except Exception as e:
                logger.error(f"Failed to index {filename}: {e}")
                
        self._is_indexed = True
        logger.info(f"Indexed {len(self._package_cache)} unique packages.")
        
    def find_jar_for_package(self, package_dot_notation: str) -> Optional[str]:
        """
        Finds the jar file name that provides the given package.
        package_dot_notation e.g., 'com.github.tartaricacid.entity'
        """
        if not self._is_indexed:
            self.index_mods()
            
        # Convert dot to slash
        package_slash = package_dot_notation.replace('.', '/')
        
        # Try finding the exact package or its parents
        parts = package_slash.split('/')
        # Minimum package parts to consider (e.g., com.xxx)
        for i in range(len(parts), 1, -1):
            sub_pkg = '/'.join(parts[:i])
            if sub_pkg in self._package_cache:
                return self._package_cache[sub_pkg]
                
        return None

    def scan_text_for_jars(self, text: str) -> Dict[str, str]:
        """
        Scan a block of text (like a stack trace) for package patterns
        and return a mapping of found packages to their respective JARs.
        """
        # Find potential package patterns: com.xxx.yyy, net.xxx.yyy, etc.
        # Simple regex for package-like strings
        patterns = re.findall(r'([a-z][a-z0-9_]*\.(?:[a-z][a-z0-9_]*\.)+[a-zA-Z0-9_]+)', text)
        found_mappings = {}
        for p in set(patterns):
            jar = self.find_jar_for_package(p)
            if jar:
                found_mappings[p] = jar
        return found_mappings
