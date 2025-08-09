import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
from collections import defaultdict, Counter

def run_git_command(args):
    """Execute git command and return stdout"""
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Git command failed: {' '.join(args)}")
        print(f"Error: {e.stderr}")
        sys.exit(1)

def get_changed_rule_files():
    """Get list of changed rule files in the PR"""
    try:
        output = run_git_command(["git", "diff", "--name-status", "origin/main...HEAD"])
        changed_files = []
        for line in output.strip().splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            status, file_path = parts
            if file_path.startswith("rules/") and file_path.endswith(".xml"):
                changed_files.append((status, Path(file_path)))
        return changed_files
    except Exception as e:
        print(f"❌ Failed to get changed files: {e}")
        sys.exit(1)

def extract_rule_ids_from_xml(content):
    """Extract rule IDs from XML content"""
    ids = []
    try:
        # Handle empty content
        if not content.strip():
            return ids
            
        # Wrap multiple root elements in a fake <root> tag to avoid parse errors
        wrapped = f"<root>{content}</root>"
        root = ET.fromstring(wrapped)
        
        for rule in root.findall(".//rule"):
            rule_id = rule.get("id")
            if rule_id and rule_id.isdigit():
                ids.append(int(rule_id))
    except ET.ParseError as e:
        print(f"⚠️ XML Parse Error: {e}")
        print(f"Content preview: {content[:200]}...")
    except Exception as e:
        print(f"⚠️ Unexpected error parsing XML: {e}")
    return ids

def get_rule_ids_per_file_in_main():
    """Get mapping of rule IDs to files in main branch"""
    try:
        run_git_command(["git", "fetch", "origin", "main"])
        files_output = run_git_command(["git", "ls-tree", "-r", "origin/main", "--name-only"])
        xml_files = [f for f in files_output.splitlines() if f.startswith("rules/") and f.endswith(".xml")]

        rule_id_to_files = defaultdict(set)
        for file in xml_files:
            try:
                content = run_git_command(["git", "show", f"origin/main:{file}"])
                rule_ids = extract_rule_ids_from_xml(content)
                for rule_id in rule_ids:
                    rule_id_to_files[rule_id].add(file)
            except subprocess.CalledProcessError:
                print(f"⚠️ Could not read {file} from main branch")
                continue
        return rule_id_to_files
    except Exception as e:
        print(f"❌ Failed to get rule IDs from main branch: {e}")
        sys.exit(1)

def get_rule_ids_from_main_version(file_path: Path):
    """Get rule IDs from main branch version of a file"""
    try:
        content = run_git_command(["git", "show", f"origin/main:{file_path.as_posix()}"])
        return extract_rule_ids_from_xml(content)
    except subprocess.CalledProcessError:
        # File might be new, return empty list
        return []

def detect_duplicates(rule_ids):
    """Detect duplicate rule IDs in a list"""
    counter = Counter(rule_ids)
    return [rule_id for rule_id, count in counter.items() if count > 1]

def print_conflicts(conflicting_ids, rule_id_to_files):
    """Print details about rule ID conflicts"""
    print("❌ Conflicts detected:")
    for rule_id in sorted(conflicting_ids):
        files = rule_id_to_files.get(rule_id, set())
        print(f"  - Rule ID {rule_id} found in:")
        for f in sorted(files):
            print(f"    • {f}")

def validate_rule_id_range(rule_ids):
    """Validate that custom rule IDs are in the recommended range"""
    invalid_ids = [rule_id for rule_id in rule_ids if not (100000 <= rule_id <= 120000)]
    if invalid_ids:
        print(f"⚠️ Warning: Rule IDs outside recommended range (100000-120000): {sorted(invalid_ids)}")
        print("  Consider using rule IDs in the range 100000-120000 for custom rules")

def main():
    """Main function to check rule ID conflicts"""
    print("🔍 Starting rule ID conflict check...")
    
    changed_files = get_changed_rule_files()
    if not changed_files:
        print("✅ No rule files were changed in this PR.")
        return

    rule_id_to_files_main = get_rule_ids_per_file_in_main()
    print(f"🔍 Checking rule ID conflicts for files: {[f.name for _, f in changed_files]}")

    for status, path in changed_files:
        print(f"\n🔎 Checking file: {path.name}")

        try:
            dev_content = path.read_text(encoding='utf-8')
            dev_ids = extract_rule_ids_from_xml(dev_content)
        except Exception as e:
            print(f"⚠️ Could not read {path.name}: {e}")
            continue

        if not dev_ids:
            print(f"ℹ️ No rule IDs found in {path.name}")
            continue

        # Validate rule ID range
        validate_rule_id_range(dev_ids)

        # Check for internal duplicates
        duplicates = detect_duplicates(dev_ids)
        if duplicates:
            print(f"❌ Duplicate rule IDs detected in {path.name}: {sorted(duplicates)}")
            sys.exit(1)

        if status == "A":
            # New file
            conflicting_ids = set(dev_ids) & set(rule_id_to_files_main.keys())
            if conflicting_ids:
                print_conflicts(conflicting_ids, rule_id_to_files_main)
                sys.exit(1)
            else:
                print(f"✅ No conflicts in new file {path.name}")

        elif status == "M":
            # Modified file
            main_ids = get_rule_ids_from_main_version(path)
            if set(dev_ids) == set(main_ids):
                print(f"ℹ️ {path.name} modified but rule IDs unchanged.")
                continue

            new_or_changed_ids = set(dev_ids) - set(main_ids)
            conflicting_ids = new_or_changed_ids & set(rule_id_to_files_main.keys())

            if conflicting_ids:
                print_conflicts(conflicting_ids, rule_id_to_files_main)
                sys.exit(1)
            else:
                print(f"✅ Modified file {path.name} has no conflicting rule IDs.")

        elif status == "D":
            # Deleted file
            print(f"ℹ️ File {path.name} was deleted.")

    print("\n✅ All rule file changes passed conflict checks.")

if __name__ == "__main__":
    main()
