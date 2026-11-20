import streamlit as st
import pandas as pd
import re
import io
import google.generativeai as genai

st.set_page_config(page_title="Menu Optimizer Pro", layout="wide", page_icon="🍽️")
st.title("🍽️ Menu Optimizer Pro - Sufra Edition")
st.markdown("أداة متقدمة لفلترة، ترجمة، وتجهيز المنيو لشيتات سفرة تلقائياً.")

# القائمة الجانبية
st.sidebar.header("⚙️ الإعدادات")
api_key = st.sidebar.text_input("أدخل Gemini API Key", type="password")
st.sidebar.markdown("---")
st.sidebar.info("هذا البرنامج يقوم بـ:\n1. حذف الأصناف الممنوعة أو بدون سعر.\n2. تحديد الأصناف المبهمة (Vague).\n3. تأليف وصف للأصناف القياسية.\n4. فصل الاختيارات (Choices).\n5. تصدير قالب سفرة النهائي.")

# رفع الملفات
col1, col2 = st.columns(2)
with col1:
    menu_file = st.file_uploader("📂 ارفع المنيو الخام (Excel)", type=["xlsx"])
with col2:
    forbidden_file = st.file_uploader("🚫 ارفع شيت الممنوعات (اختياري)", type=["xlsx", "csv"])

glossary_files = st.file_uploader("📚 ارفع شيتات القاموس (Egypt / CMT) - اختياري", type=["xlsx", "csv"], accept_multiple_files=True)

if st.button("🚀 بدء التحليل والترجمة وتجهيز الملف", use_container_width=True):
    if not api_key:
        st.error("يرجى إدخال الـ API Key في القائمة الجانبية!")
    elif not menu_file:
        st.error("يرجى رفع ملف المنيو!")
    else:
        try:
            with st.spinner("جاري معالجة البيانات وبناء شيتات سفرة... (قد يستغرق بضع دقائق)"):
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # 1. قراءة المنيو
                df = pd.read_excel(menu_file)
                
                desc_cols = [c for c in ['Short Description', 'Unnamed: 5', 'Unnamed: 6', 'Unnamed: 7'] if c in df.columns]
                if desc_cols:
                    df['Full Description'] = df[desc_cols].apply(lambda row: ' '.join(row.dropna().astype(str)), axis=1)
                    df['Full Description'] = df['Full Description'].str.replace('  ', ' ').str.strip()
                else:
                    df['Full Description'] = ""

                # 2. فلترة الأصناف بدون سعر
                if 'Price' in df.columns:
                    invalid_price_mask = df['Price'].astype(str).str.contains('N/A|Pre-order', case=False, na=True)
                    df_valid = df[~invalid_price_mask].copy()
                    df_valid['Price Num'] = df_valid['Price'].astype(str).str.extract(r'(\d+\.?\d*)').astype(float)
                else:
                    df_valid = df.copy()
                    df_valid['Price Num'] = 0

                menu_sections, menu_items, menu_label_header, menu_label_choices = [], [], [], []
                section_map = {}
                sec_id_cnt, item_id_cnt, header_id_cnt, choice_id_cnt = 1, 1, 1, 1
                
                def ai_translate_and_optimize(item_name, item_desc):
                    prompt = f"""
                    You are an expert menu translator for Egypt.
                    Item Name: "{item_name}"
                    Item Description: "{item_desc}"
                    
                    Tasks:
                    1. If description is empty, evaluate the item name. If it is standard (e.g. Lentil Soup), write a 1-sentence appetizing description. If it is vague/special (e.g. Chef's plate, Taco without protein), leave description EXACTLY as "VAGUE_ITEM".
                    2. Translate the name to Arabic.
                    3. Translate the description to Arabic.
                    
                    Return ONLY a JSON format like this, nothing else:
                    {{"name_ar": "اسم الصنف", "desc_en": "english desc", "desc_ar": "الوصف العربي"}}
                    """
                    try:
                        resp = model.generate_content(prompt).text
                        import json
                        clean_json = resp[resp.find("{"):resp.rfind("}")+1]
                        return json.loads(clean_json)
                    except:
                        return {"name_ar": item_name, "desc_en": item_desc, "desc_ar": item_desc}

                progress_bar = st.progress(0)
                total_items = len(df_valid)
                
                for idx, row in df_valid.iterrows():
                    cat = str(row.get('Category', 'General')).strip()
                    if cat not in section_map:
                        cat_ar = ai_translate_and_optimize(cat, "")["name_ar"]
                        section_map[cat] = sec_id_cnt
                        menu_sections.append({'Menu Section ID': sec_id_cnt, 'Name(Eng)': cat, 'Name(Arb)': cat_ar, 'Sort Order': sec_id_cnt})
                        sec_id_cnt += 1
                        
                    sec_id = section_map[cat]
                    name_eng = str(row.get('Item Name', '')).strip()
                    desc_eng_full = str(row.get('Full Description', '')).strip()
                    
                    choices_extracted = []
                    clean_desc_eng = desc_eng_full
                    matches = re.findall(r'\((.*?)\)', desc_eng_full)
                    for m in matches:
                        clean_desc_eng = clean_desc_eng.replace(f'({m})', '').strip()
                        parts = m.split(';')
                        for part in parts:
                            if 'beans' in part.lower():
                                opts = [o.strip() for o in re.split(r',| or | and ', part.replace('Beans:', '').replace('beans', '').strip()) if o.strip()]
                                if opts: choices_extracted.append(('Choice of Beans', opts))
                            elif 'milk' in part.lower():
                                opts = [o.strip() for o in re.split(r',| or | and ', part.replace('Milks:', '').replace('milk', '').strip()) if o.strip()]
                                if opts: choices_extracted.append(('Choice of Milk', opts))
                            else:
                                opts = [o.strip() for o in re.split(r',| or | and ', part) if o.strip()]
                                if len(opts) > 1: choices_extracted.append(('Your choice of', opts))

                    ai_result = ai_translate_and_optimize(name_eng, clean_desc_eng)
                    name_arb = ai_result.get("name_ar", name_eng)
                    final_desc_eng = ai_result.get("desc_en", clean_desc_eng)
                    final_desc_arb = ai_result.get("desc_ar", clean_desc_eng)
                    
                    if final_desc_eng == "VAGUE_ITEM":
                        final_desc_eng = ""
                        final_desc_arb = ""
                        
                    menu_items.append({
                        'Menu Section ID': sec_id, 'Menu Section Name': cat, 'Menu Item ID': item_id_cnt,
                        'Name(Eng)': name_eng, 'Name(Arb)': name_arb, 
                        'Description(Eng)': final_desc_eng, 'Description(Arb)': final_desc_arb,
                        'Price': row['Price Num'], 'Sort Order': item_id_cnt
                    })
                    
                    for choice_group, options in choices_extracted:
                        grp_ar = "اختيارك من :" if "choice" in choice_group.lower() else ai_translate_and_optimize(choice_group, "")["name_ar"]
                        menu_label_header.append({
                            'Menu Item ID': item_id_cnt, 'Menu Item Name': name_eng, 'Menu Label Header ID': header_id_cnt,
                            'Menu Label Header(Eng)': choice_group, 'Menu Label Header(Arb)': grp_ar,
                            'Min Items': 1, 'Max Items': 1, 'Sort Order': header_id_cnt
                        })
                        for opt in options:
                            opt_ar = ai_translate_and_optimize(opt, "")["name_ar"]
                            menu_label_choices.append({
                                'Menu Label Header Id': header_id_cnt, 'Menu Label Name': choice_group,
                                'Menu Label Choices ID': choice_id_cnt, 'Name(Eng)': opt, 'Name(Arb)': opt_ar,
                                'Price': 0, 'Sort Order': choice_id_cnt
                            })
                            choice_id_cnt += 1
                        header_id_cnt += 1
                        
                    item_id_cnt += 1
                    progress_bar.progress(int((idx + 1) / total_items * 100))

                df_sec = pd.DataFrame(menu_sections).reindex(columns=['Menu Section ID', 'Name(Eng)', 'Name(Arb)', 'Name(KuBa)', 'Name(KuSo)', 'Sort Order'])
                df_itm = pd.DataFrame(menu_items).reindex(columns=['Menu Section ID', 'Menu Section Name', 'Menu Item ID', 'Name(Eng)', 'Name(Arb)', 'Name(KuSo)', 'Name(KuBa)', 'Description(Eng)', 'Description(Arb)', 'Description(KuSo)', 'Description(KuBa)', 'Price', 'Sort Order'])
                df_hdr = pd.DataFrame(menu_label_header).reindex(columns=['Menu Item ID', 'Menu Item Name', 'Menu Label Header ID', 'Menu Label Header(Eng)', 'Menu Label Header(Arb)', 'Menu Label Header(KuBa)', 'Menu Label Header(KuSo)', 'Min Items', 'Max Items', 'Sort Order'])
                df_chc = pd.DataFrame(menu_label_choices).reindex(columns=['Menu Label Header Id', 'Menu Label Name', 'Menu Label Choices ID', 'Name(Eng)', 'Name(Arb)', 'Name(KuBa)', 'Name(KuSo)', 'Price', 'Sort Order'])

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_sec.to_excel(writer, sheet_name='Menu_Sections', index=False)
                    df_itm.to_excel(writer, sheet_name='Menu_Items', index=False)
                    df_hdr.to_excel(writer, sheet_name='Menu_Label_Header', index=False)
                    df_chc.to_excel(writer, sheet_name='Menu_Label_Choices', index=False)
                output.seek(0)

                st.success("🎉 تم الانتهاء بنجاح! ملفك جاهز للتحميل.")
                st.download_button(
                    label="📥 تحميل شيت سفرة النهائي (Excel)",
                    data=output,
                    file_name="Menu_Sufra_Ready.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
        except Exception as e:
            st.error(f"❌ حدث خطأ أثناء المعالجة: {e}")