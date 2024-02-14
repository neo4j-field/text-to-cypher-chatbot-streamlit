import uuid
import streamlit as st
from urllib.error import URLError
from streamlit_feedback import streamlit_feedback
import time
from service import NeoLangService

llm_avatar = 'resources/images/neo4j_icon_white.png'
user_avatar = '👤'

INITIAL_MESSAGE = [
    {
        "role": "assistant",
        "avatar": llm_avatar,
        "content": """
                    Hey there, Cummins Field Service Engineers!
                    Is there a question I can help you with?
                    """,
    },
]

RESET_MESSAGE = [
    {
        "role": "assistant",
        "avatar": llm_avatar,
        "content": """
                    Our chat history has been reset.
                    What FSE questions can I answer? 
                    """,
    },
]

with open("ui/sidebar.md", "r") as sidebar_file:
    sidebar_content = sidebar_file.read()

with open("ui/bloglist.md", "r") as sidebar_file:
    blog_list = sidebar_file.read()

try:
    st.markdown("""
    <style>
    .sidebar-font {
        font-size:14px !important;
        color:#FAFAFA !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("FSE Chatbot")
    st.sidebar.write("# FSE Chatbot", 1.0)

    if len(st.session_state.keys()) == 0:
        st.session_state["messages"] = INITIAL_MESSAGE
        st.session_state["history"] = []

    if 'session_id' not in st.session_state:
        st.session_state['session_id'] = 's-' + str(uuid.uuid4())
    # Initialize temperature in session state
    if 'llm' not in st.session_state:
        st.session_state['llm'] = "GPT-4 8k"

    if 'temperature' not in st.session_state:
        st.session_state['temperature'] = 0.7  # default value

    with st.sidebar.expander("Parameters"):
        # give options for llm
        st.session_state['llm'] = st.radio("Select LLM", ("chat-bison 32k", "GPT-4 8k"), index=1,
                                           help="""
                                    Selecting a different LLM will reset the chat. Default is GPT-4 8k.
                                    """)

        # select temperature
        st.session_state['temperature'] = st.slider("Select Temperature", 0.0, 1.0, 0.7, step=0.05,
                                                    help='''
                                            Temperature sets the amount of "creativity" the LLM has 
                                            in developing its responses. Chat must be reset to have an effect.
                                            ''')

    with st.sidebar.expander("Description"):
        st.markdown(sidebar_content)

    with st.sidebar.expander("Read More"):
        st.markdown(blog_list)

    # Add a reset button
    if st.sidebar.button("Reset Conversation", type="secondary", use_container_width=True):
        for key in st.session_state.keys():
            if key != 'session_id':
                del st.session_state[key]

        st.session_state["messages"] = RESET_MESSAGE
        st.session_state["history"] = []
        st.session_state['temperature'] = .07

    # init Communicator object
    if 'neolangservice' not in st.session_state:
        st.session_state['neolangservice'] = NeoLangService(temperature=st.session_state['temperature'],
                                                            llm_type=st.session_state['llm'])

    # Initialize the chat messages history
    if "messages" not in st.session_state:
        st.session_state["messages"] = INITIAL_MESSAGE
        st.chat_message("assistant", avatar=llm_avatar).markdown(INITIAL_MESSAGE['content'])

    # Initialize the LLM conversation
    if "llm_conversation" not in st.session_state:
        st.session_state['llm_conversation'] = st.session_state['neolangservice'].create_conversation(
            st.session_state['llm'])

    # handle llm switching
    if 'prev_llm' not in st.session_state:
        st.session_state['prev_llm'] = st.session_state['llm']

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=message['avatar']):
            st.markdown(message["content"])

    if st.session_state['prev_llm'] != st.session_state['llm']:
        print("switching llm...")
        message = f"Excuse me while I switch to my {llm} brain and wipe my memory..."
        st.chat_message("assistant", avatar=llm_avatar).markdown(message)
        st.session_state.messages.append({"role": "assistant", "avatar": llm_avatar, "content": message})
        # on switch, restart the internal llm conversation history with new llm
        st.session_state['llm_conversation'] = st.session_state['neolangservice'].create_conversation(
            st.session_state['llm'])
        st.session_state['prev_llm'] = st.session_state['llm']

    # Prompt for user input and save and display
    if question := st.chat_input():
        st.session_state.messages.append({"role": "user", "avatar": user_avatar, "content": question})
        st.chat_message("user", avatar=user_avatar).markdown(question)

        # start prompt timer
        prompt_timer_start = time.perf_counter()

        prompt = st.session_state['neolangservice'].create_prompt(question)

        prompt_timer_response = "\n\nPrompt creation took " + str(
            round(time.perf_counter() - prompt_timer_start, 4)) + " seconds."

        # create new log chain in neo4j database if fresh conversation
        # and log first user message
        # if only initial message and user message OR
        # if 2 consecutive assistant followed by new user message in history
        if len(st.session_state['messages']) <= 2 or st.session_state['messages'][-3]['role'] == 'assistant':
            message_placeholder = st.empty()
            message_placeholder.status('thinking...')
            run_timer_start = time.perf_counter()
            response = st.session_state['llm_conversation'].run(prompt)
            st.session_state['messages'].append({
                "role": "assistant",
                "avatar": llm_avatar,
                "content": response
            })

            run_timer_response = "\n\nThis thought took " + str(
                round(time.perf_counter() - run_timer_start, 4)) + " seconds."
            st.session_state['neolangservice'].log_new_conversation(llm=st.session_state['llm'], user_input=question)

        # otherwise log user message to neo4j database
        else:
            st.session_state['neolangservice'].log_user(user_input=question)

        with st.chat_message('assistant', avatar=llm_avatar):
            message_placeholder = st.empty()
            message_placeholder.status('thinking...')
            run_timer_start = time.perf_counter()
            response = st.session_state['llm_conversation'].run(prompt)
            run_timer_response = "\n\nThis thought took " + str(
                round(time.perf_counter() - run_timer_start, 4)) + " seconds."

            message_placeholder.markdown(response + prompt_timer_response + run_timer_response)
            st.session_state['neolangservice'].log_assistant(assistant_output=response, context_indices=context_idxs)

        st.session_state.messages.append({"role": "assistant", 'avatar': llm_avatar,
                                          "content": response + prompt_timer_response + run_timer_response})

    # Display chat messages from history
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=message["avatar"]):
            st.markdown(message["content"])

    # rate buttons appear after each llm response
    if len(st.session_state['messages']) > 2 and st.session_state['messages'][-1]['role'] == 'assistant':
        streamlit_feedback(
            feedback_type="thumbs",
            optional_text_label="[Required] Please provide an explanation",
            align='flex-start',
            on_submit=st.session_state['neolangservice'].rate_message,
            key='rating_options' + str(len(st.session_state['messages']))
        )
except URLError as e:
    st.error(
        """
        **This app requires internet access.**
        Connection error: %s
    """
        % e.reason
    )

except Exception as e:
    print(e)
    st.error(
        """
        Error occurred: %s
        """
        % e
    )
