import React from 'react';

const Sidebar = ({ result }) => {
  if (!result) return <div className="sidebar"><h3>🔗 Related Sections</h3></div>;

  return (
    <div className="sidebar">
      <h3>🔗 Related Sections</h3>
      <ul>
        {result.extracted_sections.map((section, index) => (
          <li key={index}>
            <strong>{section.section_title}</strong> (Page {section.page_number})<br />
            {section.refined_text}
          </li>
        ))}
      </ul>
    </div>
  );
};


export default Sidebar;
