import os

app_tsx_path = "src/App.tsx"

# 1. READ THE CURRENT APP
if not os.path.exists(app_tsx_path):
    print("❌ Error: src/App.tsx not found.")
    exit(1)

with open(app_tsx_path, "r") as f:
    content = f.read()

# 2. INJECT THE IMPORT
if "import ScarcityBar" not in content:
    content = "import ScarcityBar from './components/ScarcityBar';\n" + content
    print("✓ Imported ScarcityBar component")

# 3. INJECT THE COMPONENT (Right inside the main div or return statement)
# We look for the first return ( or <div to inject it at the top
if "<ScarcityBar />" not in content:
    # Strategy: Find the first <div> inside the App return and prepend the bar
    # This is a simple heuristic replacer for a standard React App structure
    if 'return (' in content:
        parts = content.split('return (')
        # Inject right after the opening parenthesis, assuming a fragment or div follows
        # Ideally, we want it at the top level. Let's try to inject before the first <div className="app"> or similar
        
        # Simpler approach: Replace the first <div with <><ScarcityBar /><div
        # But we need to be careful about fragments.
        
        # SAFE INJECTION: Look for the main container class we used earlier or just the first div
        import re
        # Look for the start of the JSX return
        match = re.search(r'return\s*\(\s*(<div|<main|<>)', content)
        if match:
            start_tag = match.group(1)
            # We wrap the app in a Fragment if needed, or just prepend if it's already a container
            # Let's just prepend it to the App's main div
            replacement = f"return (\n    <>\n      <ScarcityBar />\n      {start_tag[1:]}"
            # This is tricky with regex. Let's try a direct string replacement if standard vite app
            
            # Alternative: simpler split
            pre, post = content.split(start_tag, 1)
            new_content = pre + "<>\n      <ScarcityBar />\n      " + start_tag + post
            # We also need to close the fragment at the end of the return
            # Find the last ')' before the export or end of function? 
            # Actually, standard Vite App.tsx usually ends with:
            #   </div>
            # );
            # So we replace the last ); with </>\n  );\n
            
            last_paren_index = new_content.rfind(');')
            if last_paren_index != -1:
                final_content = new_content[:last_paren_index] + "    </>\n  );\n" + new_content[last_paren_index+2:]
                
                with open(app_tsx_path, "w") as f:
                    f.write(final_content)
                print("✓ ScarcityBar injected into UI hierarchy")
            else:
                print("⚠️ Could not find closing tag. Manual check recommended.")
        else:
            print("⚠️ Could not find entry point in App.tsx.")
    else:
        print("⚠️ 'return (' pattern not found.")
else:
    print("✓ ScarcityBar already present")

